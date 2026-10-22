package main

import (
	"strings"
	"testing"
)

func TestCheckCommand(t *testing.T) {
	ok := []string{
		`{"id":1,"method":"Browser.getVersion"}`,
		`{"id":2,"sessionId":"S","method":"Page.navigate","params":{"url":"https://example.com/a?b"}}`,
		`{"id":3,"method":"Target.createTarget","params":{"url":"about:blank"}}`,
		`{"id":4,"sessionId":"S","method":"Runtime.evaluate","params":{"expression":"1"}}`,
		`{"id":5,"sessionId":"S","method":"Input.dispatchDragEvent","params":{"type":"drop","data":{"items":[]}}}`,
		`{"id":6,"sessionId":"S","method":"Page.navigate","params":{"url":"data:text/html,hi"}}`,
	}
	for _, d := range ok {
		if r, _ := checkCommand(d); r != "" {
			t.Errorf("refused %s: %s", d, r)
		}
	}
	bad := []string{
		`{"id":1,"sessionId":"S","method":"Page.navigate","params":{"url":"file:///C:/Users/"}}`,
		`{"id":1,"method":"Page.navigate","params":{"url":"  FILE:///etc/passwd"}}`,
		`{"id":1,"method":"Target.createTarget","params":{"url":"chrome://settings"}}`,
		`{"id":1,"method":"Page.navigate","params":{"url":"view-source:file:///etc/passwd"}}`,
		`{"id":1,"method":"Page.navigate","params":{"url":"brave://settings"}}`,
		`{"id":1,"method":"Browser.setDownloadBehavior","params":{"behavior":"allow","downloadPath":"C:\\Startup"}}`,
		`{"id":1,"method":"Page.setDownloadBehavior","params":{"behavior":"allow"}}`,
		`{"id":1,"method":"DOM.setFileInputFiles","params":{"files":["C:\\x"]}}`,
		`{"id":1,"method":"Input.dispatchDragEvent","params":{"type":"drop","data":{"items":[],"files":["/etc/passwd"]}}}`,
		`{"id":1,"method":"Browser.grantPermissions","params":{"permissions":["clipboardReadWrite"]}}`,
		`{"id":1,"method":"PWA.install","params":{}}`,
		`{"id":1,"method":"Extensions.loadUnpacked","params":{"path":"/x"}}`,
		`{"id":1,"method":"Network.loadNetworkResource","params":{"url":"https://x"}}`,
		`{"id":1,"method":"Target.exposeDevToolsProtocol","params":{}}`,
		`not json`,
		`{"id":1,"method":"Runtime.evaluate","params":{"expression":"` + strings.Repeat("a", maxCommand) + `"}}`,
	}
	for _, d := range bad {
		if r, _ := checkCommand(d); r == "" {
			t.Errorf("allowed %.120s", d)
		}
	}
	_, c := checkCommand(`{"id":7,"sessionId":"S","method":"PWA.install"}`)
	if got := string(refusal(c, "no")); got != `{"error":{"code":-32000,"message":"no"},"id":7,"sessionId":"S"}` {
		t.Errorf("refusal %s", got)
	}
}
