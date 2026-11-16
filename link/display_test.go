package main

import "testing"

func TestPickDisplay(t *testing.T) {
	l := []display{{Name: "a"}, {Name: "b", Main: true}, {Name: "c"}}
	for want, got := range map[int]int{-1: 1, 0: 0, 2: 2, 5: 1} {
		if g := pickDisplay(l, want); g != got {
			t.Errorf("pickDisplay(%d) = %d, want %d", want, g, got)
		}
	}
	if pickDisplay([]display{{Name: "only"}}, -1) != 0 {
		t.Error("no main screen: the first one")
	}
}

func TestLiveViewAndScreenFrames(t *testing.T) {
	be := newFakeBackend()
	be.info.Displays = []display{{Name: "Display 1", W: 1920, H: 1080, Main: true}, {Name: "Display 2", W: 2560, H: 1440}}
	a := newAgent(&Config{Server: "https://ui.example.com"}, be, testLog)
	var said []string
	a.say = func(_ lineKind, m string) { said = append(said, m) }
	one := 1
	a.handle(request{T: "watch", On: true})
	a.handle(request{T: "watch", On: true})
	a.serve(request{T: "shot", Live: true})
	a.handle(request{T: "display", I: &one})
	a.handle(request{T: "watch", On: false})
	want := []string{"Live view: your screen is shown in Harness Maxxing", "Screen: Display 2 (2560x1440)", "Live view closed"}
	if len(said) != len(want) {
		t.Fatalf("live log: %q", said)
	}
	for i := range want {
		if said[i] != want[i] {
			t.Fatalf("live log: %q", said)
		}
	}
	if !slicesContains(be.ops, "display 1") {
		t.Fatalf("ops: %v", be.ops)
	}
}

func slicesContains(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}
