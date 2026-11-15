param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$source = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class UsbDkDiagnostic
{
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint OPEN_EXISTING = 3;
    private const uint USBDK_DEVICE_TYPE = 50000;
    private const uint FILE_READ_ACCESS = 1;
    private const uint METHOD_BUFFERED = 0;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool DeviceIoControl(
        SafeFileHandle device,
        uint controlCode,
        IntPtr inputBuffer,
        uint inputBufferSize,
        out uint outputBuffer,
        uint outputBufferSize,
        out uint bytesReturned,
        IntPtr overlapped);

    private static uint CtlCode(uint deviceType, uint function, uint method, uint access)
    {
        return (deviceType << 16) | (access << 14) | (function << 2) | method;
    }

    public static string Run()
    {
        using (SafeFileHandle handle = CreateFile(
            @"\\.\UsbDk",
            GENERIC_READ | GENERIC_WRITE,
            0,
            IntPtr.Zero,
            OPEN_EXISTING,
            0,
            IntPtr.Zero))
        {
            if (handle.IsInvalid)
            {
                int error = Marshal.GetLastWin32Error();
                return "OPEN_FAILED win32=" + error + " message=" + new Win32Exception(error).Message;
            }

            uint count;
            uint bytesReturned;
            uint ioctl = CtlCode(USBDK_DEVICE_TYPE, 0x851, METHOD_BUFFERED, FILE_READ_ACCESS);
            bool ok = DeviceIoControl(
                handle,
                ioctl,
                IntPtr.Zero,
                0,
                out count,
                sizeof(uint),
                out bytesReturned,
                IntPtr.Zero);

            if (!ok)
            {
                int error = Marshal.GetLastWin32Error();
                return "COUNT_FAILED win32=" + error + " message=" + new Win32Exception(error).Message;
            }

            return "COUNT_OK devices=" + count + " bytes=" + bytesReturned;
        }
    }
}
'@

Add-Type -TypeDefinition $source -Language CSharp
$result = [UsbDkDiagnostic]::Run()
Set-Content -LiteralPath $OutputPath -Value $result -Encoding UTF8

