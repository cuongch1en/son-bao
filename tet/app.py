from urllib.parse import urlparse
from flask import Flask, request, render_template, redirect, url_for, flash
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
import requests
import sqlite3
import json
import os
import difflib
import re


app = Flask(__name__, template_folder='templates')
app.secret_key = 'supersecretkey'
scheduler = BackgroundScheduler()
scheduler.start()

DATABASE = 'database.db'
BLACKLIST = ['hacked by','seized by']

def get_db():
    conn = sqlite3.connect(DATABASE)
    return conn


def init_db():
    with app.app_context():
        db = get_db()
        with open('schema.sql', 'r') as f:
            db.cursor().executescript(f.read())
        db.commit()


if not os.path.exists(DATABASE):
    init_db()


def content_diff(last_content, new_content):
    text1_lines = last_content.splitlines()
    text2_lines = new_content.splitlines()

    # Create a Differ object
    differ = difflib.Differ()

    # Compare the texts
    diff = list(differ.compare(text1_lines, text2_lines))

    added_lines = ''
    removed_lines = ''

    for line in diff:
        if line.startswith("+ "):
            if line[2:]:
                added_lines += line[2:]+'\n'
        elif line.startswith("- "):
            if line[2:]:
                removed_lines += line[2:]+'\n'
    if added_lines or removed_lines:
        return '(added lines)\n\n' + added_lines + '\n(removed lines)\n\n' + removed_lines
    else:
        return ''

def send_discord_alert(url, content, title):
    webhook_url = 'https://discord.com/api/webhooks/1246398591480893612/4zPHh3usIAihz9aT5krAOsF2v-NGCx-N2yOrhnDgVVUMOz8IzAjDFil6daGMrtL_4k4J'
    data = {
        "username": f"ROBOT alerted {title}\n",
        "content": f"Change detected on {url}\n{content}"
    }
    requests.post(webhook_url, data=json.dumps(data), headers={
                  "Content-Type": "application/json"})


def get_valid_domain(soup):

    valid_domain = []
    srcs = soup.findAll(attrs={'src': True})
    hrefs = soup.findAll(attrs={'href': True})

    for i in [urlparse(tag['src']).netloc for tag in srcs]:
        if i != "":
            valid_domain.append(i)

    for i in [urlparse(tag['href']).netloc for tag in hrefs]:
        if i != "":
            valid_domain.append(i)

    return list(sorted(set(valid_domain)))


def check_web_pages(soup):

    valid_domain = []
    srcs = soup.findAll(attrs={'src': True})
    hrefs = soup.findAll(attrs={'href': True})

    for i in [urlparse(tag['src']).netloc for tag in srcs]:
        if i != "":
            valid_domain.append(i)

    for i in [urlparse(tag['href']).netloc for tag in hrefs]:
        if i != "":
            valid_domain.append(i)

    return list(sorted(set(valid_domain)))


def is_valid_url(url):
    # Check if the URL points to an image or JS file
    x = re.search(
        r'\.(css|jpg|jpeg|png|gif|bmp|webp|svg|ico|woff2|js|pdf)$', url, re.IGNORECASE)
    if x:
        return True
    else:
        return False


def url_check(url):

    min_attr = ('scheme', 'netloc')
    try:
        result = urlparse(url)
        if all([result.scheme, result.netloc]):
            return True
        else:
            return False
    except:
        return False


def crawl_all_pages(soup, url):
    valid_domain = []
    hrefs = soup.findAll(attrs={'href': True})
    if url[-1] != '/':
        url = url+'/'

    for i in [urlparse(tag['href']).path for tag in hrefs]:
        if i != "":
            if url_check(i):

                if url in i:
                    if not is_valid_url(i):
                        valid_domain.append(i)
            else:
                if not is_valid_url(i):
                    if i[0] != '/':
                        valid_domain.append(url+i)
                    else:
                        valid_domain.append(url+i[1:])

    return list(sorted(set(valid_domain)))

def check_all_pages(soup, url):
    
    valid_domains = crawl_all_pages(soup, url)

    alert = ''

    for page in valid_domains:
        response = requests.get(page)
        soup = BeautifulSoup(response.text, 'html.parser')
        content = soup.get_text()
        
        for i in BLACKLIST:
            
            if i in content:
                alert += page + " contains words from BLACKLIST\n"
    return alert

def check_for_change(target_id):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id, url, last_content , valid_domain FROM targets WHERE id = ?", (target_id,))
    target = cur.fetchone()
    if not target:
        return

    response = requests.get(target[1])
    soup = BeautifulSoup(response.text, 'html.parser')

    new_content = soup.get_text()
    new_domain = " ".join(get_valid_domain(soup))

    if target[3] != new_domain:
        send_discord_alert(url=target[1], content="",
                           title="CRITICAL RISK - UNKNOWN DOMAIN")
    else:
        alert = content_diff(target[2], new_content)
        alert += check_all_pages(soup,target[1])

        if alert:
            send_discord_alert(url=target[1], content=alert, title="")


@app.route('/')
def index():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, url FROM targets")
    targets = cur.fetchall()
    return render_template('index.html', targets=targets)


@app.route('/add_target', methods=['GET', 'POST'])
def add_target():
    if request.method == 'POST':
        url = request.form['url']
        interval = int(request.form['interval'])
        db = get_db()
        cur = db.cursor()
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        last_content = soup.get_text()
        valid_domain = " ".join(get_valid_domain(soup))
        cur.execute("INSERT INTO targets (url,last_content,valid_domain) VALUES (?,?,?)",
                    (url, last_content, valid_domain, ))
        db.commit()
        target_id = cur.lastrowid
        scheduler.add_job(func=check_for_change, trigger="interval",
                          seconds=interval, args=[target_id], id=str(target_id),max_instances=2)
        flash('Target added successfully!')
        return redirect(url_for('index'))
    return render_template('add_target.html')


@app.route('/view_target/<int:target_id>')
def view_target(target_id):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT url, last_content FROM targets WHERE id = ?", (target_id,))
    target = cur.fetchone()
    return render_template('view_target.html', target=target)


@app.route('/remove_target/<int:target_id>')
def remove_target(target_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM targets WHERE id = ?", (target_id,))
    db.commit()
    scheduler.remove_job(str(target_id))
    flash('Target removed successfully!')
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=58)
