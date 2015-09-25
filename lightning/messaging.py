"Generic docstring A"
import smtplib
from email.mime.text import MIMEText

class Email(object):
    'Generic docstring A'
    def __init__(self, host, username, password, default_from, default_to, environment):
        self.host = host
        self.username = username
        self.password = password
        self.default_from = default_from
        self.default_to = default_to
        self.environment = environment

    def send(self, subject, message, recipients=None):
        'Generic docstring A'
        if recipients is None:
            recipients = [self.default_to]

        msg = MIMEText(message)
        msg['Subject'] = subject
        msg['From'] = self.default_from
        msg['to'] = ','.join(recipients)

        try:
            if (self.environment not in ['test', 'dev', 'local']):
                smtp = smtplib.SMTP(self.host)
                smtp.login(self.username, self.password)
                smtp.sendmail(self.default_from, recipients, msg.as_string())
                smtp.close()
        except Exception:
            return False
        return True
