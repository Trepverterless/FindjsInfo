# FindjsInfo

对JSINFO-SCAN优化了下， 把递归新域名和检测 敏感文件 增加 可选参数，同时借鉴JSFinderAAA 新增对 api接口的状态进行简单检测。

- 添加了简单的web请求，简单的API判断
- 增加可选参数  --skip_sub  ，--scan_leak ，--scan_newdomain
- 优化html中 js 文件的提取正则表达式,优化完整 url 的拼接错误
- 优化避免对找到的link 链接都去递归查找是否存在其他js文件，默认不对找到的api递归查找其他js，要查找需要指定--scan_deep参数
- USAGE：python3 .\FindjsInfo.py --target "[https://www.baidu.com](https://www.baidu.com/)" 









- 原项目：https://github.com/msfisgood/JSFinderAAA

  ​                https://github.com/p1g3/JSINFO-SCAN