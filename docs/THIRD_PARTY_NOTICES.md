# 第三方代码声明

游戏日常管家（GameButler）里移植或附带了下面这些开源项目的代码，按各自的许可证使用。

## Snap Hutao Remastered（MIT License）

- 项目：https://github.com/SnapHutaoRemasteringProject/Snap.Hutao.Remastered
- 用在：`butler/mys.py`（米游社扫码登录、stoken 换 cookie_token / ltoken、查原神角色、米游社每日签到、DS 签名）。
  照着原项目的 C# 代码改写成 Python：接口地址、请求头、签名算法和盐、活动编号都来自原项目
  （HoyoPlayPassportClient.cs、PassportClient.cs、UserInitializationService.cs、AuthClient.cs、BindingClient.cs、
  SignInClient.cs、DataSignAlgorithm.cs、DataSignOptions.cs、HoyolabOptions.cs、SaltConstants.cs、ApiEndpoints.csv）。
- 没有移植：设备指纹（原代码注明不要照搬那段设备信息）、极验人机验证。

```
MIT License

Copyright (c) 2022-2025 DGP Studio
Copyright (c) 2026 DGP Studio (Snap.Nicole)
Copyright (c) 2026 Snap.HutaoRemasteringProject

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## QR Code Generator for JavaScript（MIT License）

- 项目：https://github.com/kazuhikoarase/qrcode-generator（npm：qrcode-generator 1.4.4）
- 用在：`static/js/vendor-qrcode.js`（原样附带，用来在界面上画米游社登录二维码）。

```
Copyright (c) 2009 Kazuhiko Arase

URL: http://www.d-project.com/

Licensed under the MIT license:
  http://www.opensource.org/licenses/mit-license.php

The word 'QR Code' is registered trademark of DENSO WAVE INCORPORATED
  http://www.denso-wave.com/qrcode/faqpatent-e.html

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
