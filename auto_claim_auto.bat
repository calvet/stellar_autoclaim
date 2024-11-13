@echo off

SET tribunal=auto_claim_stellar

Title "Fechando batch dos %tribunal%.."

taskkill /F /FI "WindowTitle eq  Administrator:  \"%tribunal%\"" /T

Title "Batch do %tribunal% fechado!"

Title "%tribunal%"

set logfile=%~dp0\log.log
echo started at %date% %time% >> %logfile%
python %~dp0/auto_claim.py

pause
