@echo off
title Push QueueForge to GitHub
cd /d "%~dp0"
echo Pushing QueueForge Nexus to https://github.com/dhruvahari27/-QueueForge- ...
git push -u origin main
pause
