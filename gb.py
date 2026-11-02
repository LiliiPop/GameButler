"""游戏日常管家入口。用法见 butler/main.py。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 嵌入式 python 不会自动加脚本目录

from butler.main import main

if __name__ == "__main__":
    main()
