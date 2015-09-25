
from string import Template
from pprint import pprint

main_template = """
[group:lightning_web]
programs=$program_refrences

$program_list
"""

program_template = """
[program:lightning_web-$port]
environment=NEW_RELIC_CONFIG_FILE='/var/www/lightning/conf/newrelic-preprod.ini'
command=newrelic-admin run-program /var/www/lightning/bin/lightning preprod  --port=$port --loadtest
directory=/var/www/lightning
user=lightning
autostart=false
autorestart=true
redirect_stderr=false
stdout_logfile=/var/log/lightning.log
stderr_logfile=/var/log/lightning_error.log
loglevel=info

"""

def generate_program_references(start_port, end_port):
    refs = ""
    for port in range(start_port, end_port + 1):
        refs += "lightning_web-%s" % port
        #pprint(dict(port=port, end_port=end_port, ne=port != end_port))

        if port != end_port:
            refs += ","
    return refs

def generate_program_list(start_port, end_port):
    programs = ""
    for port in range(start_port, end_port + 1):
        s = Template(program_template)
        programs += s.safe_substitute(port=port)
    return programs


def print_config():
    start = 5000
    end = 5014
    refs = generate_program_references(start, end)
    programs = generate_program_list(start, end)
    s = Template(main_template)
    print s.substitute(program_refrences=refs, program_list=programs)


print_config()
