//go:build windows

package main

import (
	"errors"
	"sync"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

const jobMsgActiveProcessZero = 4 // JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO

type jobAssocCompletionPort struct {
	CompletionKey  uintptr
	CompletionPort windows.Handle
}

// proc is a browser started inside a Job Object: every process it spawns belongs to the job,
// the job is terminated as a whole (same effect as taskkill /T /F, without running taskkill),
// and the job reports when its last process is gone (no polling).
type proc struct {
	pid     int
	done    chan struct{}
	job     windows.Handle
	port    windows.Handle
	process windows.Handle
	once    sync.Once
}

func startBrowser(path string, args []string) (*proc, error) {
	job, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return nil, err
	}
	fail := func(e error) (*proc, error) { windows.CloseHandle(job); return nil, e }
	info := windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION{}
	// If the agent dies, the job handle closes and the browser goes with it.
	info.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	if _, err := windows.SetInformationJobObject(job, windows.JobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&info)), uint32(unsafe.Sizeof(info))); err != nil {
		return fail(err)
	}
	port, err := windows.CreateIoCompletionPort(windows.InvalidHandle, 0, 0, 1)
	if err != nil {
		return fail(err)
	}
	assoc := jobAssocCompletionPort{CompletionKey: uintptr(job), CompletionPort: port}
	if _, err := windows.SetInformationJobObject(job, windows.JobObjectAssociateCompletionPortInformation,
		uintptr(unsafe.Pointer(&assoc)), uint32(unsafe.Sizeof(assoc))); err != nil {
		windows.CloseHandle(port)
		return fail(err)
	}
	app, err := windows.UTF16PtrFromString(path)
	if err != nil {
		windows.CloseHandle(port)
		return fail(err)
	}
	cl, err := windows.UTF16PtrFromString(windows.ComposeCommandLine(append([]string{path}, args...)))
	if err != nil {
		windows.CloseHandle(port)
		return fail(err)
	}
	si := windows.StartupInfo{}
	si.Cb = uint32(unsafe.Sizeof(si))
	var pi windows.ProcessInformation
	// Suspended until it is in the job, so no child can escape it.
	if err := windows.CreateProcess(app, cl, nil, nil, false, windows.CREATE_SUSPENDED, nil, nil, &si, &pi); err != nil {
		windows.CloseHandle(port)
		return fail(err)
	}
	if err := windows.AssignProcessToJobObject(job, pi.Process); err != nil {
		windows.TerminateProcess(pi.Process, 1)
		windows.CloseHandle(pi.Thread)
		windows.CloseHandle(pi.Process)
		windows.CloseHandle(port)
		return fail(err)
	}
	windows.ResumeThread(pi.Thread)
	windows.CloseHandle(pi.Thread)
	p := &proc{pid: int(pi.ProcessId), done: make(chan struct{}), job: job, port: port, process: pi.Process}
	go func() {
		defer close(p.done)
		for {
			var code uint32
			var key uintptr
			var ov *windows.Overlapped
			err := windows.GetQueuedCompletionStatus(port, &code, &key, &ov, windows.INFINITE)
			if err != nil {
				if errors.Is(err, windows.ERROR_ABANDONED_WAIT_0) || errors.Is(err, windows.ERROR_INVALID_HANDLE) {
					return // port closed by release()
				}
				// fall back to the main process handle
				windows.WaitForSingleObject(p.process, windows.INFINITE)
				return
			}
			if key == uintptr(job) && code == jobMsgActiveProcessZero {
				return
			}
		}
	}()
	return p, nil
}

func (p *proc) kill(grace time.Duration) {
	_ = windows.TerminateJobObject(p.job, 1)
	select {
	case <-p.done:
	case <-time.After(grace):
	}
}

func (p *proc) release() {
	p.once.Do(func() {
		windows.CloseHandle(p.job)
		windows.CloseHandle(p.port)
		windows.CloseHandle(p.process)
	})
}
