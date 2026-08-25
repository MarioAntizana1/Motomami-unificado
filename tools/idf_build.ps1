# Helper para build del direccionales (ESP-IDF v6.0.2 puro)
# Uso: powershell -ExecutionPolicy Bypass -File tools\idf_build.ps1 <build|flash|monitor> [args...]
param(
    [Parameter(Mandatory=$true, Position=0)][string]$Action,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$ExtraArgs
)
$env:IDF_PATH = "C:\esp\v6.0.2\esp-idf"
$env:ESP_IDF_VERSION = "6.0.2"
$env:IDF_PYTHON_ENV_PATH = "C:\Users\wenup\.espressif\python_env\idf6.0_py3.14_env"
& "C:\esp\v6.0.2\esp-idf\export.ps1" | Out-Null
Push-Location "C:\Users\wenup\Documents\Rpi-motomami-ultimate\Motomami-esp32\Motomami-direccionales-esp32c6"
& idf.py $Action @ExtraArgs
$code = $LASTEXITCODE
Pop-Location
exit $code
