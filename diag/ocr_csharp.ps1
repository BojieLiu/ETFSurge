param(
    [Parameter(Mandatory = $true)][string]$ImagePath
)
$cs = @'
using System;
using System.IO;
using System.Threading.Tasks;
using Windows.Media.Ocr;
using Windows.Storage;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;
using Windows.Globalization;

public static class WinOcr {
    public static async Task<string> Run(string path) {
        var file = await StorageFile.GetFileFromPathAsync(path);
        using (var stream = await file.OpenAsync(FileAccessMode.Read)) {
            var decoder = await BitmapDecoder.CreateAsync(stream);
            var bitmap = await decoder.GetSoftwareBitmapAsync();
            var lang = new Language("zh-Hans");
            OcrEngine engine = OcrEngine.TryCreateFromLanguage(lang);
            if (engine == null) engine = OcrEngine.TryCreateFromUserProfileLanguages();
            if (engine == null) return "<<NO_OCR_ENGINE>>";
            var result = await engine.RecognizeAsync(bitmap);
            var sb = new System.Text.StringBuilder();
            foreach (var line in result.Lines) sb.AppendLine(line.Text);
            return sb.ToString();
        }
    }
}
'@
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -TypeDefinition $cs -ReferencedAssemblies @("System.Runtime.WindowsRuntime")
$task = [WinOcr]::Run((Resolve-Path $ImagePath).Path)
$task.GetAwaiter().GetResult()
