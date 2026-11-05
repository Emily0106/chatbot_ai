#!/bin/bash
cd apps/frontend
nohup python3 -m http.server 3000 > ../../frontend_manual.log 2>&1 &
echo "Frontend started with PID $!"
