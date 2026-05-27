@echo off
chcp 65001 > nul
title Vintage Daily Digest - 프로덕션 동기화
powershell.exe -ExecutionPolicy Bypass -File "%~dp0sync-prod.ps1"
