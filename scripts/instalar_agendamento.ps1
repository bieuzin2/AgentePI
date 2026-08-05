# Cria a tarefa semanal de vigilancia no Windows Task Scheduler.
# Terca-feira as 20h (pos-RPI, que sai as tercas). O vigia 5 (exterior) so roda
# na primeira terca do mes -- essa logica fica dentro de vigilancia/executar.py
# (primeira_terca_do_mes), nao em duas tarefas agendadas separadas.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File scripts\instalar_agendamento.ps1
#
# Requer execucao como administrador (Register-ScheduledTask grava em nivel de
# sistema). Idempotente: se a tarefa ja existir, e substituida.

$ErrorActionPreference = "Stop"

$Raiz = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
$Nome = "VigilanciaPatentesINPI"

if (-not (Test-Path $Python)) {
    throw "Python do venv nao encontrado em $Python. Rode a partir da raiz do repo com .venv criado."
}

$Acao = New-ScheduledTaskAction -Execute $Python `
    -Argument "-m vigilancia.executar" -WorkingDirectory $Raiz

$Gatilho = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At 20:00

$Config = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $Nome -Action $Acao -Trigger $Gatilho `
    -Settings $Config -Description `
    "Vigilancia autonoma INPI/EPO (docs/plano-v2.md 4.1): reingestao + 5 vigias + e-mail de alerta." `
    -Force

Write-Host "Tarefa '$Nome' instalada: toda terca as 20h."
Write-Host "Confira com: Get-ScheduledTask -TaskName '$Nome'"
Write-Host "Rode manualmente para testar: Start-ScheduledTask -TaskName '$Nome'"
