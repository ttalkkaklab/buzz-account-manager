// Windows GUI entry point and per-agent launcher. No third-party packages.
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

func fail(err error) {
	message := "Buzz Account Manager could not start. Reinstall the application.\n" + err.Error()
	if strings.HasPrefix(filepath.Base(os.Args[0]), "launch-agent-") {
		fmt.Fprintln(os.Stderr, message)
	} else {
		user32 := syscall.NewLazyDLL("user32.dll")
		body, _ := syscall.UTF16PtrFromString(message)
		title, _ := syscall.UTF16PtrFromString("Buzz Account Manager")
		user32.NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(body)), uintptr(unsafe.Pointer(title)), 0x10)
	}
	os.Exit(1)
}
func main() {
	exe, err := os.Executable()
	if err != nil {
		fail(err)
	}
	folder := filepath.Dir(exe)
	name := strings.TrimSuffix(filepath.Base(exe), ".exe")
	var command *exec.Cmd
	if strings.HasPrefix(name, "launch-agent-") {
		data, err := os.ReadFile(filepath.Join(folder, "installation.txt"))
		if err != nil {
			fail(err)
		}
		installation := strings.TrimSpace(string(data))
		args := append([]string{"-X", "utf8", filepath.Join(folder, "manager-backend.py"), "launch", strings.TrimPrefix(name, "launch-")}, os.Args[1:]...)
		command = exec.Command(filepath.Join(installation, "runtime", "python.exe"), args...)
		command.Stdin, command.Stdout, command.Stderr = os.Stdin, os.Stdout, os.Stderr
	} else {
		ps := filepath.Join(os.Getenv("SystemRoot"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
		command = exec.Command(ps, "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(folder, "App.ps1"))
	}
	command.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8")
	// CREATE_NO_WINDOW suppresses the console without hiding the first WinForms window.
	// STARTF_USESHOWWINDOW/SW_HIDE also hides App.ps1's ShowDialog when launched from an icon.
	command.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000}
	if err := command.Run(); err != nil {
		if exit, ok := err.(*exec.ExitError); ok {
			os.Exit(exit.ExitCode())
		}
		fail(err)
	}
}
