#!/bin/bash
# OCR 应用启动脚本
# 使用方法：
#   ./run.sh    

source /home/ubuntu/minerU/.venv/bin/activate && cd /home/ubuntu/s3-ocr-mineru && PYTHONPATH=src python -m uvicorn src.api_server:app --host 0.0.0.0 --port 8000 2>&1
