#!/usr/bin/env python
"""

fabric-graphite is a fabric script to install Graphite, Nginx, uwsgi and all dependencies on a debian-based host.

Plus, for a limited time, statsd support!

To execute:

    * Make sure you have fabric installed on your local host (e.g. pip install fabric)
    * run `fab graphite_install -H root@{hostname}` 
      (hostname should be the name of a virtual server you're installing onto)

It might prompt you for the root password on the host you are trying to instal onto.

Best to execute this on a clean virtual machine running Debian 6 (Squeeze). 
Also tested successfully on Ubuntu 12.04 VPS.

"""

from fabric.api import cd, sudo, run, put, settings, task, prompt


def check_sudo():
    with settings(warn_only=True):
        result = sudo('pwd')
        if result.failed:
            print "Trying to install sudo. Must be root"
            run('apt-get update && apt-get install -y sudo')  

@task
def graphite_install():
    """
    Installs Graphite and dependencies
    """
    check_sudo()

    web_server_pref = prompt("Run graphite-web under nginx or apache?",
                             default="nginx")

    install_deps(web_server_pref)

    # TODO can't install cairo as ubuntu package?
    # install_cairo()

    install_giraffe_dash()



    # setting the carbon config files (default)
    with cd('/opt/graphite/conf/'):
        sudo('cp carbon.conf.example carbon.conf')
        sudo('cp storage-schemas.conf.example storage-schemas.conf')


    # initializing graphite django db
    with cd('/opt/graphite/webapp/graphite'):
        sudo("python manage.py syncdb")

    # changing ownership on graphite folders
    sudo('chown -R www-data: /opt/graphite/')

    # clearing old carbon log files
    put('config/carbon-logrotate', '/etc/cron.daily/', use_sudo=True)

    # put startup script
    put('config/carbon', '/etc/init.d/', use_sudo=True)
    sudo('chmod ugo+x /etc/init.d/carbon')
    sudo('cd /etc/init.d && update-rc.d carbon defaults')

    if web_server_pref == "nginx":
        # starting nginx
        sudo('nginx')
        # starting uwsgi
        sudo('supervisorctl update && supervisorctl start uwsgi')
        configure_for_nginx()
    else:
        configure_for_apache()
        sudo("apache2ctl restart")

    # starting carbon-cache
    sudo('/etc/init.d/carbon start')

def install_deps(web_server):
    sudo('apt-get update')
    sudo('apt-get install -y %s' % get_dependency_packages(web_server))

    sudo('pip install whisper')
    sudo('pip install carbon')
    sudo('pip install graphite-web')

    sudo('pip install simplejson') # required for django admin
    sudo('pip install django==1.3')
    sudo('pip install django-tagging')

def get_dependency_packages(web_server):
    if web_server == "nginx":
        return  ("apache2 apache2-mpm-worker apache2-utils "
                "apache2.2-bin apache2.2-common build-essential git libapr1 "
                "libaprutil1 libaprutil1-dbd-sqlite3 python3.2 "
                "libpython3.2 python3.2-minimal libapache2-mod-wsgi "
                "libaprutil1-ldap memcached python-cairo-dev "
                "python-ldap python-memcache "
                "python-pysqlite2 python-pip sqlite3 erlang-os-mon "
                "erlang-snmp rabbitmq-server bzr")

    else:
        return  ("apache2 apache2-mpm-worker apache2-utils "
                 "apache2.2-bin apache2.2-common build-essential "
                 "git libapache2-mod-wsgi libapr1 "
                 "libaprutil1 libaprutil1-dbd-sqlite3 python "
                 "python-dev libapache2-mod-wsgi "
                 "libaprutil1-ldap memcached python-cairo-dev "
                 "python-ldap python-memcache "
                 "python-pysqlite2 python-pip sqlite3 erlang-os-mon "
                 "erlang-snmp rabbitmq-server "
                 "bzr expect ssh")


def configure_for_nginx():
    # Downloading PCRE source (Required for nginx)
    with cd('/usr/local/src'):
        sudo('wget ftp://ftp.csx.cam.ac.uk/pub/software/programming/pcre/pcre-8.32.tar.gz')
        sudo('tar -zxvf pcre-8.32.tar.gz')

    # creating nginx etc and log folders
    sudo('mkdir -p /etc/nginx')
    sudo('mkdir -p /var/log/nginx')
    sudo('chown -R www-data: /var/log/nginx')

    # creating automatic startup scripts for nginx
    put('config/nginx', '/etc/init.d/', use_sudo=True)
    sudo('chmod ugo+x /etc/init.d/nginx')
    sudo('cd /etc/init.d && update-rc.d nginx defaults')


    # installing uwsgi from source
    with cd('/usr/local/src'):
        sudo('wget http://projects.unbit.it/downloads/uwsgi-1.4.3.tar.gz')
        sudo('tar -zxvf uwsgi-1.4.3.tar.gz')
    with cd('/usr/local/src/uwsgi-1.4.3'):
        sudo('make')

        sudo('cp uwsgi /usr/local/bin/')
        sudo('cp nginx/uwsgi_params /etc/nginx/')

    # downloading nginx source
    with cd('/usr/local/src'):
        sudo('wget http://nginx.org/download/nginx-1.2.6.tar.gz')
        sudo('tar -zxvf nginx-1.2.6.tar.gz')

    # installing nginx
    with cd('/usr/local/src/nginx-1.2.6'):
        sudo('./configure --prefix=/usr/local --with-pcre=/usr/local/src/pcre-8.32/ --with-http_ssl_module --with-http_gzip_static_module --conf-path=/etc/nginx/nginx.conf --pid-path=/var/run/nginx.pid --lock-path=/var/lock/nginx.lock --error-log-path=/var/log/nginx/error.log --http-log-path=/var/log/nginx/access.log --user=www-data --group=www-data')
        sudo('make && make install')

    # copying nginx and uwsgi configuration files
    put('config/nginx.conf', '/etc/nginx/', use_sudo=True)
    put('config/uwsgi.conf', '/etc/supervisor/conf.d/', use_sudo=True)


def configure_for_apache():
    # enable modules
    sudo("a2enmod info")
    sudo("a2enmod wsgi")

    # enable site
    with cd("/opt/graphite/conf"):
        run("sudo cp carbon.conf.example carbon.conf")
        run("sudo cp storage-schemas.conf.example storage-schemas.conf")

    with settings(warn_only = True):
        sudo("rm /etc/apache2/sites-enabled/000-default")

    # fix path in vhost conf
    sudo(("sed -i 's/run\/wsgi/\/var\/run\/apache2\/wsgi/g' "
          "/opt/graphite/examples/example-graphite-vhost.conf"))

    sudo(("ln -s -v "
        "/opt/graphite/examples/example-graphite-vhost.conf "
        "/etc/apache2/sites-enabled/graphite"))

def install_cairo():
    # creating a folder for downloaded source files
    sudo('mkdir -p /usr/local/src')

    # installing pixman
    with cd('/usr/local/src'):
        sudo('wget http://cairographics.org/releases/pixman-0.28.2.tar.gz')
        sudo('tar -zxvf pixman-0.28.2.tar.gz')
    with cd('/usr/local/src/pixman-0.28.2'):
        sudo('./configure && make && make install')
    # installing cairo
    with cd('/usr/local/src'):
        sudo('wget http://cairographics.org/releases/cairo-1.12.8.tar.xz')
        sudo('tar -Jxf cairo-1.12.8.tar.xz')
    with cd('/usr/local/src/cairo-1.12.8'):
        sudo('./configure && make && make install')
    # installing py2cairo (python 2.x cairo)
    with cd('/usr/local/src'):
        sudo('wget http://cairographics.org/releases/py2cairo-1.8.10.tar.gz')
        sudo('tar -zxvf py2cairo-1.8.10.tar.gz')
    with cd('/usr/local/src/pycairo-1.8.10'):
        sudo('./configure --prefix=/usr && make && make install')
        sudo('echo "/usr/local/lib" > /etc/ld.so.conf.d/pycairo.conf')
        sudo('ldconfig')

def install_giraffe_dash():
    with cd('/opt/graphite/webapp'):
        sudo('git clone git://github.com/kenhub/giraffe.git')

