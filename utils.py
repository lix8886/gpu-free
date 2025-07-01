import smtplib
from smtplib import SMTP_SSL
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sender_QQ = "xx@qq.com"
sender_PWD = "xx"

class AutoEmail:

    def __init__(
        self,
        host_server="smtp.qq.com",
        sender_qq=sender_QQ,
        pwd=sender_PWD,
        receiver=sender_QQ,
        mail_title="[GPU 空闲通知]",
    ):
        self.host_server = host_server  # qq邮箱smtp服务器
        self.sender_qq = sender_qq  # 发件人邮箱
        self.pwd = pwd  # 授权码
        self.receiver = receiver  # 收件人邮箱
        self.mail_title = mail_title  # 邮件标题
        self.reset_sources()

        self.img_count = 0

    def addcontext(self, context):
        # 普通文本内容
        self.msg.attach(MIMEText(context + "\n", "plain", "utf-8"))

    def reset_sources(self, srcs=[]):
        self.resource = srcs
        self.msg = MIMEMultipart()
        self.msg["Subject"] = Header(self.mail_title, "utf-8")
        self.msg["From"] = self.sender_qq
        self.msg["To"] = Header("GPU 空闲通知]", "utf-8")

    def send(self, receiver=None):

        # 文本数据
        for c in self.resource:
            self.addcontext(c)

        # 发送数据
        try:
            smtp = SMTP_SSL(self.host_server)
            smtp.set_debuglevel(0)
            _ = smtp.ehlo(self.host_server)
            _ = smtp.login(self.sender_qq, self.pwd)
            _ = smtp.sendmail(
                self.sender_qq, receiver or self.receiver, self.msg.as_string()
            )
            _ = smtp.quit()
            print("邮件发送成功")
        except smtplib.SMTPException:
            print("无法发送邮件")
