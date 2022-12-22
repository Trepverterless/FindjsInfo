import argparse
import asyncio
import os
import re
import sys
import threading
from asyncio import CancelledError
from queue import Queue
from urllib.parse import urlparse
import json
import aiohttp
from loguru import logger
from tldextract import extract
import socket
from html import unescape
import time
from bs4 import BeautifulSoup 



socket.setdefaulttimeout(20)


class JSINFO:
    def argparser(self):
        """解析参数"""
        parser = argparse.ArgumentParser(description='JSINFO can help you find the information hidden in JS and '
                                                     'expand the scope of your assets.',
                                         epilog='\tUsage:\npython ' + sys.argv[
                                             0] + " --target www.baidu.com --keywords baidu")
        parser.add_argument('--target', help='A target like www.example.com or subdomains.txt',required=True)
        parser.add_argument('--keywords', help='Keyword will be split in "," to extract subdomain')
        parser.add_argument('--black_keywords', help='Black keywords in html source')
        parser.add_argument('--skip_sub', help='skip subdomain find',action="store_true")
        parser.add_argument('--scan_leak', help='scan leak find',action="store_true")
        parser.add_argument('--scan_newdomain', help='scan finded newdomain',action="store_true")
        parser.add_argument('--scan_deep', help='scan all find link',action="store_true")
        # parser.add_argument('--only_this', help='only scan this domain and under  ',action="store_true")
        args = parser.parse_args()
        return args

    def __init__(self):

        self.banner()
        args = self.argparser()

        """初始化参数"""
        self.queue = Queue()
        self.root_domains = []

        self.timeout = 10    #设置请求超时时间
      
        self.scan_newdomain = args.scan_newdomain
        self.skip_sub = args.skip_sub    
        self.scan_leak = args.scan_leak
        self.scan_deep = args.scan_deep
        # self.only_this = True #args.only_this
        target = args.target
       
        if not target.startswith(('http://', 'https://')) and not os.path.isfile(target):
            target = 'http://' + target
        elif os.path.isfile(target):
            with open(target, 'r+', encoding='utf-8') as f:
                for domain in f:
                    domain = domain.strip()
                    if not domain.startswith(('http://', 'https://')):
                        self.root_domains.append(domain)
                        domain = 'http://www.' + domain
                        self.queue.put(domain)
        if args.keywords is None:
            keyword = extract(target).domain
        else:
            keyword = args.keywords
        self.keywords = keyword.split(',')
        if args.black_keywords is not None:
            self.black_keywords = args.black_keywords.split(',')
        else:
            self.black_keywords = []

        self.black_extend_list = ['png', 'jpg', 'gif', 'jpeg', 'ico', 'svg', 'bmp', 'mp3', 'mp4', 'avi', 'mpeg', 'mpg',
                                  'mov', 'zip', 'rar', 'tar', 'gz', 'mpeg', 'mkv', 'rmvb', 'iso', 'css', 'txt', 'ppt',
                                  'dmg', 'app', 'exe', 'pem', 'doc', 'docx', 'pkg', 'pdf', 'xml', 'eml''ini', 'so',
                                  'vbs', 'json', 'webp', 'woff', 'ttf', 'otf', 'log', 'image', 'map', 'woff2', 'mem',
                                  'wasm', 'pexe', 'nmf']
        self.black_filename_list = ['jquery', 'bootstrap', 'react', 'vue', 'google-analytics']
        self.extract_urls = []
        self._value_lock = threading.Lock()
        self.leak_infos = []  # 存储元祖，每个元素对应为：敏感信息正则名称、敏感信息值、敏感信息来源页面
        self.leak_infos_match = []
        """将用户输入存入队列中"""
        if not os.path.isfile(target):
            self.queue.put(target)

        """最终返回的信息列表"""
        self.jsnum = {}
        self.apinum = 0
        self.sub_domains = []

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/79.0.3945.130 Safari/537.36'}
        """正则"""
        link_pattern = r"""
            (?:"|')                               # Start newline delimiter
            (
                ((?:[a-zA-Z]{1,10}://|//)           # Match a scheme [a-Z]*1-10 or //
                [^"'/]{1,}\.                        # Match a domainname (any character + dot)
                [a-zA-Z]{2,}[^"']{0,})              # The domainextension and/or path
                |
                ((?:/|\.\./|\./)                    # Start with /,../,./
                [^"'><,;| *()(%%$^/\\\[\]]          # Next character can't be...
                [^"'><,;|()]{1,})                   # Rest of the characters can't be
                |
                ([a-zA-Z0-9_\-/]{1,}/               # Relative endpoint with /
                [a-zA-Z0-9_\-/]{1,}                 # Resource name
                \.(?:[a-zA-Z]{1,4}|action)          # Rest + extension (length 1-4 or action)
                (?:[\?|/][^"|']{0,}|))              # ? mark with parameters
                |
                ([a-zA-Z0-9_\-]{1,}                 # filename
                \.(?:php|asp|aspx|jsp|json|
                    action|html|js|txt|xml)             # . + extension
                (?:\?[^"|']{0,}|))                  # ? mark with parameters
            )
            (?:"|')                               # End newline delimiter
		"""
        self.link_pattern = re.compile(link_pattern, re.VERBOSE)
        self.js_pattern =  '<script[^<>]*?src="?(.*?\.js)"?[^<>]*?>.*?<\/script>'      #'src=["\'](.*?)["\']'
        self.href_pattern = 'href=["\'](.*?)["\']'
        self.leak_info_patterns = {'mail': r'([-_a-zA-Z0-9\.]{1,64}@%s)', 'author': '@author[: ]+(.*?) ',
                                   'accesskey_id': 'accesskeyid.*?["\'](.*?)["\']',
                                   'accesskey_secret': 'accesskeyid.*?["\'](.*?)["\']',
                                   'access_key': 'access_key.*?["\'](.*?)["\']', 'google_api': r'AIza[0-9A-Za-z-_]{35}',
                                   'google_captcha': r'6L[0-9A-Za-z-_]{38}|^6[0-9a-zA-Z_-]{39}$',
                                   'google_oauth': r'ya29\.[0-9A-Za-z\-_]+',
                                   'amazon_aws_access_key_id': r'AKIA[0-9A-Z]{16}',
                                   'amazon_mws_auth_toke': r'amzn\\.mws\\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                                   'amazon_aws_url': r's3\.amazonaws.com[/]+|[a-zA-Z0-9_-]*\.s3\.amazonaws.com',
                                   'amazon_aws_url2': r"("r"[a-zA-Z0-9-\.\_]+\.s3\.amazonaws\.com"r"|s3://[a-zA-Z0-9-\.\_]+"r"|s3-[a-zA-Z0-9-\.\_\/]+"r"|s3.amazonaws.com/[a-zA-Z0-9-\.\_]+"r"|s3.console.aws.amazon.com/s3/buckets/[a-zA-Z0-9-\.\_]+)",
                                   'facebook_access_token': r'EAACEdEose0cBA[0-9A-Za-z]+',
                                   'authorization_basic': r'basic [a-zA-Z0-9=:_\+\/-]{5,100}',
                                   'authorization_bearer': r'bearer [a-zA-Z0-9_\-\.=:_\+\/]{5,100}',
                                   'authorization_api': r'api[key|_key|\s+]+[a-zA-Z0-9_\-]{5,100}',
                                   'mailgun_api_key': r'key-[0-9a-zA-Z]{32}',
                                   'twilio_api_key': r'SK[0-9a-fA-F]{32}',
                                   'twilio_account_sid': r'AC[a-zA-Z0-9_\-]{32}',
                                   'twilio_app_sid': r'AP[a-zA-Z0-9_\-]{32}',
                                   'paypal_braintree_access_token': r'access_token\$production\$[0-9a-z]{16}\$[0-9a-f]{32}',
                                   'square_oauth_secret': r'sq0csp-[ 0-9A-Za-z\-_]{43}|sq0[a-z]{3}-[0-9A-Za-z\-_]{22,43}',
                                   'square_access_token': r'sqOatp-[0-9A-Za-z\-_]{22}|EAAA[a-zA-Z0-9]{60}',
                                   'stripe_standard_api': r'sk_live_[0-9a-zA-Z]{24}',
                                   'stripe_restricted_api': r'rk_live_[0-9a-zA-Z]{24}',
                                   'github_access_token': r'[a-zA-Z0-9_-]*:[a-zA-Z0-9_\-]+@github\.com*',
                                   'rsa_private_key': r'-----BEGIN RSA PRIVATE KEY-----',
                                   'ssh_dsa_private_key': r'-----BEGIN DSA PRIVATE KEY-----',
                                   'ssh_dc_private_key': r'-----BEGIN EC PRIVATE KEY-----',
                                   'pgp_private_block': r'-----BEGIN PGP PRIVATE KEY BLOCK-----',
                                   'json_web_token': r'ey[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*$',
                                   'slack_token': r"\"api_token\":\"(xox[a-zA-Z]-[a-zA-Z0-9-]+)\"",
                                   'SSH_privKey': r"([-]+BEGIN [^\s]+ PRIVATE KEY[-]+[\s]*[^-]*[-]+END [^\s]+ PRIVATE KEY[-]+)",
                                   'possible_Creds': r"(?i)("r"password\s*[`=:\"]+\s*[^\s]+|"r"password is\s*[`=:\"]*\s*[^\s]+|"r"pwd\s*[`=:\"]*\s*[^\s]+|"r"passwd\s*[`=:\"]+\s*[^\s]+)", }

        """输出传入的Target以及Keywords"""
        if not os.path.isfile(target):
            logger.info('[+]Target ==> {}'.format(target))
        else:
            logger.info('[+]Target ==> {}'.format(self.root_domains))
        logger.info('[+]Keywords ==> {}'.format(self.keywords))
        logger.info('[+]Black Keywords ==> {}'.format(self.black_keywords))

    def banner(self):
        """输出banner"""
        banner = r""" _____  ___    _  _   _  ___    _____ 
  _____ _           _  _     ___        __       
 |  ___(_)____   __| |(_)___|_ _|_ __  / _| ___  
 | |_  | | __ \ / _` || / __|| || '_ \| |_ / _ \ 
 |  _| | | | | | (_| || \__ \| || | | |  _| (_) |
 |_|   |_|_| |_|\__,_|/ |___/___|_| |_|_|  \___/ 
                    |__/                         
        Author： https://github.com/Trepverterless/FindjsInfo
            """
        print(banner)

    def start(self):
        firstpage = True
        loop = asyncio.get_event_loop()
        while self.queue.qsize() > 0:
            try:
                while not self.queue.empty():   #对页面信息进行递归扫描提取api
                    tasks = []
                    i = 0
                    while i < 50 and not self.queue.empty():
                        """获取基本信息"""
                        url = self.queue.get()
                        """根据文件后缀创建异步任务列表"""
                        filename = os.path.basename(url)
                        file_extend = self.get_file_extend(filename)
                        if file_extend == 'js':      
                            tasks.append(asyncio.ensure_future(self.FindLinkInJs(url)))
                        else:
                            tasks.append(asyncio.ensure_future(self.FindLinkInPage(url,firstpage)))
                            if firstpage == True:
                                firstpage == False
                        i += 1
                    """开始跑异步任务"""
                    if tasks:
                        loop.run_until_complete(asyncio.wait(tasks))
                    logger.info('-' * 20)
                    logger.info('[+]root domain count ==> {}'.format(len(self.root_domains)))
                    logger.info('[+]sub domain count ==> {}'.format(len(self.sub_domains)))
                    logger.info('[+]js count ==> {}'.format(len(self.jsnum)))
                    logger.info('[+]api count ==> {}'.format(self.apinum))
                    logger.info('[+]leakinfos count ==> {}'.format(len(self.leak_infos)))
                    logger.info('-' * 20)
            except KeyboardInterrupt:
                logger.info('[+]Break From Queue.')
                break
            except CancelledError:
                pass

        logger.info('[+]All root domain count ==> {}'.format(len(self.root_domains)))
        logger.info('[+]All sub domain count ==> {}'.format(len(self.sub_domains)))
        logger.info('[+]All js count ==> {}'.format(len(self.jsnum)))
        logger.info('[+]All api count ==> {}'.format(self.apinum))
        logger.info('[+]All leakinfos count ==> {}'.format(len(self.leak_infos)))

        now_time = str(int(time.time()))
        with open(now_time + '_rootdomain', 'a+', encoding='utf-8') as f:     #输出结果到文件
            for i in self.root_domains:
                f.write(i.strip() + '\n')

        with open(now_time + '_subdomain', 'a+', encoding='utf-8') as f:
            for i in self.sub_domains:
                f.write(i.strip() + '\n')

        with open(now_time + '_apis', 'a+', encoding='utf-8') as f:   
            for j in self.jsnum:
                f.write(j.strip() + '\n'+'='*60+'\n')
                for i in self.jsnum[j]:
                    if len(str(i[0])) >100:
                        f.write('{}    title: {}   status:{}    body_size: {}    is_api: {} '.format(str(i[0]).strip(),str(i[1]),str(i[2]),str(i[3]),str(i[4])))
                    else:
                        f.write('{:<100s}    title: {}   status:{}    body_size: {}    is_api: {} '.format(str(i[0]).strip(),str(i[1]),str(i[2]),str(i[3]),str(i[4])))
                    f.write('\n')
                f.write('\n\n')

        with open(now_time + '_leakinfos', 'a+', encoding='utf-8') as f:
            for i in self.leak_infos:
                i = str(i)
                f.write(i.strip() + '\n')

        logger.info('[+]Root domains ==> {}'.format(now_time + '_rootdomain'))
        logger.info('[+]Sub domains ==> {}'.format(now_time + '_subdomain'))
        logger.info('[+]Apis ==> {}'.format(now_time + '_apis'))
        logger.info('[+]LeakInfos ==> {}'.format(now_time + '_leakinfos'))

    async def FindLinkInPage(self, url,isfirst):   # 在页面中查找信息
        """发起请求"""
        try:
            resp = await self.send_request(url)
        except ConnectionResetError:
            return None
        if not resp:
            return None
        if self.black_keywords:
            for black_keyword in self.black_keywords:
                if black_keyword in resp:
                    return False
        self.find_leak_info(url, resp)  # 探测敏感信息

        """从页面中获取href以及js_urls"""
        try:
            hrefs = re.findall(self.href_pattern, resp)
        except TypeError:
            hrefs = []
        try:
            js_urls = re.findall(self.js_pattern, resp)
        except TypeError:
            js_urls = []
        try:
            js_texts = re.findall('<script>(.*?)<\/script>', resp)
        except TypeError:
            js_texts = []

        """获取完整的url"""
        parse_url = urlparse(url)
        for href in hrefs:
            full_href_url = await self.extract_link(parse_url, href,isfirst)
            if full_href_url is False:
                continue
        for js_url in js_urls:
            full_js_url = await self.extract_link(parse_url, js_url,isfirst)
            if full_js_url is False:
                continue
        for js_text in js_texts:
            await self.FindLinkInJsText(url, js_text)
        logger.info('Find new page:{}'.format(url))

    async def FindLinkInJs(self, url):    #在js文件进行查找
        resp = await self.send_request(url)
        if not resp:
            return False
        if self.black_keywords:
            for black_keyword in self.black_keywords:
                if black_keyword in resp:
                    return False
        self.find_leak_info(url, resp)  # 探测敏感信息
        try:
            link_finder_matchs = re.finditer(self.link_pattern, str(resp))
        except:
            return None
        for match in link_finder_matchs:
            match = match.group().strip('"').strip("'")
            full_api_url = await self.extract_link(urlparse(url), match)
            if full_api_url is False:
                continue
        logger.info('Find new js:{}'.format(url))

    async def FindLinkInJsText(self, url, text):            #在匹配的<script>文本中查找link
        try:
            link_finder_matchs = re.finditer(self.link_pattern, str(text))
        except:
            return None
        self.find_leak_info(url, text)  # 探测敏感信息
        for match in link_finder_matchs:
            match = match.group().strip('"').strip("'")
            full_api_url =await self.extract_link(urlparse(url), match)
            if full_api_url is False:
                continue

    async def send_request(self, url):
        """解决asyncio的历史遗留BUG"""
        sem = asyncio.Semaphore(1024)
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with sem:
                    async with session.get(url, timeout=self.timeout, headers=self.headers) as req:
                        # await asyncio.sleep(1)
                        response = await req.text('utf-8', 'ignore')
                        req.close()
                        return response
        except CancelledError:
            pass
        except ConnectionResetError:
            pass
        except Exception as e:
            logger.warning('[-]Resolve {} fail'.format(url))
            return False

    def filter_black_extend(self, file_extend):
        if file_extend in self.black_extend_list:
            return True

    def get_file_extend(self, filename):
        return filename.split('/')[-1].split('?')[0].split('.')[-1].lower()

    def get_format_url(self, parse_link, filename, file_extend):
        if '-' in filename:
            split_filename = filename.split('-')
        elif '_' in filename:
            split_filename = filename.split('_')
        else:
            split_filename = filename.split('-')

        format_filename = ''
        for split_name in split_filename:
            try:
                load_json = json.loads(split_name)
                if isinstance(load_json, int) or isinstance(load_json, float):
                    format_filename += '-int'
            except:
                format_filename += split_name
        return parse_link.scheme + '://' + parse_link.netloc + parse_link.path.replace(filename, format_filename)

    def tofullurl(self, parse_url, link):    #转换查找的路径，拼接成完整路径
        filename = os.path.basename(link)
        file_extend = self.get_file_extend(filename)
        if link.startswith(('http://', 'https://')) and file_extend not in self.black_extend_list:
            full_url = link
        elif link.startswith('javascript:'):
            return False
        elif link.startswith('////') and len(link) > 4:
            full_url = 'http://' + link[2:]
        elif link.startswith('//') and len(link) > 2:
            full_url = 'http:' + link
        elif link.startswith('/'):
            full_url = parse_url.scheme + '://' + parse_url.netloc + link
        elif link.startswith('./'):
            if parse_url.path[-1:] == '/':
                parse_url
                full_url = parse_url.scheme + '://' + parse_url.netloc + parse_url.path + link[1:]
            else:
                full_url = parse_url.scheme + '://' + parse_url.netloc + os.path.dirname(parse_url.path) + link[1:]
        else:
            full_url = parse_url.scheme + '://' + parse_url.netloc + os.path.dirname(parse_url.path) + '/' + link
        return full_url,filename

    async def extract_link(self, parse_url, link,isfirst=False):
        """html解码"""
        link = unescape(link)
        """判断后缀是否在黑名单中"""

        is_link = False
        full_url,filename = self.tofullurl(parse_url,link)
        file_extend = self.get_file_extend(filename)
        if file_extend in self.black_extend_list:    
            return False

        """解析爬取到链接的域名和根域名"""
        extract_full_url_domain = extract(full_url)
        root_domain = extract_full_url_domain.domain + '.' + extract_full_url_domain.suffix
        sub_domain = urlparse(full_url).netloc
        """判断爬取到的链接是否满足keyword"""
        in_keyword = False
        for keyword in self.keywords:    #判断是否在root根域名中
            if keyword in root_domain:
                in_keyword = True
        if not in_keyword:
            return False
        """添加根域名"""
        try:
            self._value_lock.acquire()
            if  self.scan_newdomain == True:  #是否跳过递归查询其他域名
                if root_domain not in self.root_domains:
                    self.root_domains.append(root_domain)
                    logger.info('[+]Find a new root domain ==> {}'.format(root_domain))
                    if root_domain not in self.extract_urls:
                        self.extract_urls.append(root_domain)
                        self.queue.put('http://' + root_domain)
            else:
                pass
        finally:
            self._value_lock.release()

        """添加子域名"""
        try:
            self._value_lock.acquire()
            if  self.skip_sub == False:  #是否跳过递归查询子域名
                if sub_domain not in self.sub_domains and sub_domain != root_domain:
                    self.sub_domains.append(sub_domain)
                    logger.info('[+]Find a new subdomain ==> {}'.format(sub_domain))
                    if sub_domain not in self.extract_urls:
                        self.extract_urls.append(sub_domain)
                        self.queue.put('http://' + sub_domain)
            else:
                pass
        finally:
            self._value_lock.release()

        if is_link is True:
            return link
        try:         
            #self._value_lock.acquire()
            if full_url not in self.jsnum and file_extend != 'html' and file_extend != 'js':
                domain_rul = parse_url.scheme + '://' + parse_url.netloc + parse_url.path 
                titile,sCode,state,isapi = await self.getUrlStatus(full_url)    #检测api访问响应状态
                tmp = [full_url,titile,sCode,state,isapi]
                if domain_rul in self.jsnum:
                    self.jsnum[domain_rul].append(tmp)     #记录api
                    self.apinum += 1
                    #logger.info('[+]api count ==> {}'.format(self.apinum))
                else:
                    self.jsnum[domain_rul] = [tmp]
                # logger.info('[+]Find a new api in {}'.format(parse_url.netloc))
        except Exception as e:
            logger.warning(e)
        finally:
            pass
            #self._value_lock.release()

        format_url = self.get_format_url(urlparse(full_url), filename, file_extend)

        try:
            self._value_lock.acquire()       #添加新的递归查询页面
            if format_url not in self.extract_urls:
                if (self.scan_deep == True) or (link.startswith(('http://', 'https://'))) or (isfirst==True):     
                    self.extract_urls.append(format_url)
                    self.queue.put(full_url)                 
                    logger.info('Find new link:  {}'.format(full_url))                   
                    
        finally:
            self._value_lock.release()

    def find_leak_info(self, url, text):   #查找文件中存在的 敏感信息
        if self.scan_leak == False:
            return 
        for k in self.leak_info_patterns.keys():
            pattern = self.leak_info_patterns[k]
            if k == 'mail':
                for netloc in self.root_domains:
                    mail_pattern = '([-_a-zA-Z0-9\.]{1,64}@%s)' % netloc
                    self.process_pattern(k, mail_pattern, text, url)
            else:
                self.process_pattern(k, pattern, text, url)

    def process_pattern(self, key, pattern, text, url):
        try:
            self._value_lock.acquire()
            matchs = re.findall(pattern, text, re.IGNORECASE)
            for match in matchs:
                match_tuple = (key, match, url)
                if match not in self.leak_infos_match:
                    self.leak_infos.append(match_tuple)
                    self.leak_infos_match.append(match)
                    # logger.info('[+]Find a leak info ==> {}'.format(match_tuple))
        except Exception as e:
            logger.warning(e)
        finally:
            self._value_lock.release()

    async def getUrlStatus(self,url):   #验证接口信息
 
        sem = asyncio.Semaphore(1024)
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with sem:
                    async with session.get(url, timeout=self.timeout, headers=self.headers) as req:
                        #await asyncio.sleep(1)
                        res = await req.text()   

                        sCode = req.status
                        bodySize = len(res)
                        req.close()

                        r = BeautifulSoup(res,"html.parser") 
                        if r.title:
                            title = r.title.string
                        else:
                            title = "N/A"

        except	Exception as result:
            
            logger.warning(result)
            return 'erro','erro','erro',False
        
        if '{"' == res[0:2]:
            apiData = True
        else:
            apiData = False
        
     
        return title,sCode,bodySize,apiData


if __name__ == '__main__':
    JSINFO().start()
