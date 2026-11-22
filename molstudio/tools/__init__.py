# -*- coding: utf-8 -*-
"""随程序分发的外部脚本（独立可执行，不 import molstudio）。

目前只有 ``gau_xtb.py``：高斯 ``external=`` 接口用来调用 xTB 的桥脚本。
它由 Gaussian 用外部 Python 直接执行，所以**不能**依赖本包里的任何模块。
"""
