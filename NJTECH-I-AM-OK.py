"""
@Author: NephrenCake
@Date: 2022/5/11
@Desc: NJTECH-I-AM-OK
"""
import argparse
import time
import requests
import json
import logging

import schedule
from bs4 import BeautifulSoup
import ddddocr


def json_to_dict(path):
    with open(path, 'rt', encoding='utf-8') as jsonFile:
        return json.load(jsonFile)


def get_logger():
    import sys
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s : %(message)s"))

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(sh)
    return logger


def email_exception(subject="打卡出错", email_notice=True):
    def wrapper(func):
        import functools
        @functools.wraps(func)
        def inner(*args, **kwargs):
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            import smtplib
            import traceback

            self = args[0]
            try:
                res = func(*args, **kwargs)
                return res
            except Exception:
                text = "\n" + traceback.format_exc()
                logging.error(text)
                if email_notice and self.email["sender"] != "":
                    # > https://blog.csdn.net/MATLAB_matlab/article/details/106240424
                    # > py使用qq邮箱
                    msg = MIMEMultipart()
                    msg.attach(MIMEText(text, 'plain', 'utf-8'))
                    msg['Subject'] = subject
                    msg['From'] = self.email["sender"]
                    s = smtplib.SMTP_SSL(self.email["host"], self.email["port"])
                    s.login(self.email["sender"], self.email["passwd"])
                    s.sendmail(self.email["sender"], self.email["receivers"], msg.as_string())
                    logging.error("邮件已发送")
                return

        return inner

    return wrapper


class GoldenFairy:
    def __init__(self, conf_path="config.json"):
        self.conf = json_to_dict(conf_path)
        self.email = self.conf["email"]
        self.logger = get_logger()

        self.session = requests.Session()

        self.headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-cn',
            'Connection': 'timeout=5',
            "Content-Type": "application/json",
            "User-Agent": "User-Agent: Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; rv:11.0) like Gecko",
        }

    def login(self, service=None, channelshow=None):
        if service is None:
            service = "https://u.njtech.edu.cn/oauth2/authorize"

        url = f'https://u.njtech.edu.cn/cas/login'
        # 获取i南工登录页面
        response = self.session.get(
            url=url,
            params={
                "service": service
            }
        )

        # 淦验证码
        captcha_response = self.session.get(
            url="https://u.njtech.edu.cn/cas/captcha.jpg",
            params={
                "service": service
            }
        )
        # image = cv2.imdecode(np.frombuffer(captcha_response.content, np.uint8), cv2.IMREAD_COLOR)
        # cv2.imshow("dfsdf", image)
        # cv2.waitKey(0)
        ocr = ddddocr.DdddOcr()
        ocr_res = ocr.classification(captcha_response.content)
        self.logger.info(ocr_res)

        soup = BeautifulSoup(response.content, "html.parser")
        lt0 = soup.find('input', attrs={'name': 'lt'})['value']
        execution0 = soup.find('input', attrs={'name': 'execution'})['value']
        channel = {
            "校园内网": "default",
            "中国移动": "@cmcc",
            "中国电信": "@telecom"
        }
        login_info = self.conf["loginInfo"]
        channelshow = login_info["channelshow"] if channelshow is None else channelshow

        # 登录
        response = self.session.post(
            url=url,
            params={
                "service": service
            },
            data={
                'username': login_info['username'],
                'password': login_info['password'],
                'channelshow': channelshow,
                'channel': channel[channelshow],
                'lt': lt0,
                'execution': execution0,
                '_eventId': 'submit',
                'login': '登录',
                'captcha': ocr_res
            },
            allow_redirects=False
        )

        if "Expires" in response.headers.keys():
            self.logger.info(f"成功连接校园网，成功连接[{channelshow}]")

        return response

    def logout(self):
        url = "https://u.njtech.edu.cn/oauth2/logout?redirect_uri=https://i.njtech.edu.cn/index.php/njtech/logout"
        self.session.get(url=url)
        self.session.close()

    @email_exception(subject="健康打卡出错")
    def health(self):
        self.logger.info("开始健康打卡")

        service = "http://pdc.njtech.edu.cn/#/dform/genericForm/wbfjIwyK"
        response = self.login(service=service, channelshow="校园内网")

        # 1. 获取 token
        ticket = response.headers['Location'].split('?ticket=')[-1].split('#/')[0]
        response = self.session.get(
            url=f"http://pdc.njtech.edu.cn/dfi/validateLogin",
            params={
                "ticket": ticket,
                "service": service
            },
            headers=self.headers,
        )
        self.headers["Referer"] = f"http://pdc.njtech.edu.cn/?ticket={ticket}"
        self.headers["Authentication"] = json.loads(response.content)['data']['token']

        # 2. 获取wid
        response = self.session.get(
            "http://pdc.njtech.edu.cn/dfi/formOpen/loadFormListBySUrl",
            params={
                "sUrl": "wbfjIwyK"
            },
            headers=self.headers,
        )
        wid = json.loads(response.content)['data'][0]['WID']

        # 3. 获取最近一次提交数据
        response = self.session.get(
            f"http://pdc.njtech.edu.cn/dfi/formData/loadFormFillHistoryDataList",
            params={
                "formWid": wid,
            },
            headers=self.headers,
        )
        last_data: dict = json.loads(response.content)["data"][0]

        # 4. 发送表单数据
        if 'ONEIMAGEUPLOAD_KWYTQFT3' not in last_data or 'ONEIMAGEUPLOAD_KWYTQFT5' not in last_data:
            self.logger.error("健康码或身份码过期")  # 判断健康码、行程码是否过期

        post_data = {
            "auditConfigWid": "",
            "commitDate": time.strftime("%Y-%m-%d", time.localtime()),
            "commitMonth": time.strftime("%Y-%m", time.localtime()),
            "dataMap": {
                "wid": "",
                "RADIO_KWYTQFSU": "本人知情承诺",  # 知情承诺
                "INPUT_KWYTQFSO": last_data['INPUT_KWYTQFSO'],  # 学号
                "INPUT_KWYTQFSP": last_data['INPUT_KWYTQFSP'],  # 姓名
                "SELECT_KX3ZXSAE": last_data['SELECT_KX3ZXSAE'],  # 学院
                "INPUT_KWYTQFSS": last_data['INPUT_KWYTQFSS'],  # 班级
                "INPUT_KX3ZXSAD": last_data['INPUT_KX3ZXSAD'],  # 手机号
                "INPUT_KWYUM2SI": last_data['INPUT_KWYUM2SI'],  # 辅导员
                "RADIO_KWYTQFSZ": last_data['RADIO_KWYTQFSZ'],  # 当前位置
                "RADIO_KWYTQFT0": last_data['RADIO_KWYTQFT0'],  # 所在省市区
                "CASCADER_KWYTQFT1": last_data['CASCADER_KWYTQFT1'][1:-1].split(', '),
                "RADIO_KWYTQFT2": last_data['RADIO_KWYTQFT2'],  # 身体状况
                "ONEIMAGEUPLOAD_KWYTQFT3": last_data['ONEIMAGEUPLOAD_KWYTQFT3'][1:-1].split(', '),  # 健康码
                "ONEIMAGEUPLOAD_KWYTQFT5": last_data['ONEIMAGEUPLOAD_KWYTQFT5'][1:-1].split(', '),  # 行程码
                "LOCATION_KWYTQFT7": last_data['LOCATION_KWYTQFT7'],  # 定位
            },
            "formWid": wid,
            "userId": "AM@" + str(int(time.time() * 1000)),
        }

        response = self.session.post(
            'http://pdc.njtech.edu.cn/dfi/formData/saveFormSubmitData',
            data=json.dumps(post_data).encode("utf-8"),
            headers=self.headers,
            allow_redirects=False
        )

        response = json.loads(response.content)
        self.logger.info(post_data)
        if response["message"] == "请求成功":
            self.logger.info("健康打卡提交成功！")
        else:
            self.logger.warning("健康打卡提交失败！")
            self.logger.warning(response)
            raise Exception

        # 退出连接
        self.logout()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', type=str, default='1', help='1: 仅连接校园网  2: 连接校园网并打卡  3: 定时打卡')
    opt = parser.parse_args()

    gf = GoldenFairy()
    if opt.mode == "1":
        gf.login()
        # python -u NJTECH-I-AM-OK.py --mode "1"
    elif opt.mode == "2":
        gf.health()
        # python -u NJTECH-I-AM-OK.py --mode "2"
    elif opt.mode == "3":
        schedule.every().day.at("07:00:00").do(gf.health)
        while True:
            schedule.run_pending()
            time.sleep(1)
        # nohup python3 -u NJTECH-I-AM-OK.py --mode "3" > output.log 2>&1 &
