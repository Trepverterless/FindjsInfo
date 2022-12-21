# FindjsInfo

对JSINFO-SCAN优化了下， 把递归新域名和检测 敏感文件 增加 可选参数，同时借鉴JSFinderAAA 新增对 api接口的状态进行简单检测。

- 添加了简单的web请求，简单的API判断
- 增加可选参数  --skip_sub  ，--scan_leak ，--scan_newdomain
- USAGE：python3 .\FindjsInfo.py --target "[https://www.baidu.com](https://www.baidu.com/)" 









- 原项目：https://github.com/msfisgood/JSFinderAAA

  ​                https://github.com/p1g3/JSINFO-SCAN