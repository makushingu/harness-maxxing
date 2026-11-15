// stamp appends a pairing trailer to a Harness Link binary, like the server does for each download:
//
//	go run ./tools/stamp dist/harness-link-linux-amd64 /tmp/harness-link https://ui.example.com AB12CD34
//
// Layout at the end of the file: <json {"server","code"}><uint32 big-endian len(json)>HMLINK01.
package main

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"os"
)

func main() {
	if len(os.Args) != 5 {
		fmt.Fprintln(os.Stderr, "usage: stamp IN OUT SERVER CODE")
		os.Exit(2)
	}
	in, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	j, _ := json.Marshal(map[string]string{"server": os.Args[3], "code": os.Args[4]})
	out := append(in, j...)
	out = binary.BigEndian.AppendUint32(out, uint32(len(j)))
	out = append(out, "HMLINK01"...)
	if err := os.WriteFile(os.Args[2], out, 0o755); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
