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
BLACKLIST = ['hacked', 'seized']


def get_db():
    conn = sqlite3.connect(DATABASE)
    
    # conn.execute("DROP TABLE IF EXISTS targets")

    return conn
def clear_db():
    db = get_db()
    db.execute("DROP TABLE IF EXISTS targets")
    db.commit()
    init_db()

def init_db():
    with app.app_context():
        db = get_db()
        with open('schema.sql', 'r') as f:
            db.cursor().executescript(f.read())
        db.commit()


if not os.path.exists(DATABASE):
    init_db()
else:
    clear_db()


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

    if len(content) >= 2000:
        content = content[0:1900]

    data = {
        "username": f"ROBOT alerted {title}\n",
        "content": f"Change detected on {url}\n{content}"
    }
    requests.post(webhook_url, data=json.dumps(data), headers={
                  "Content-Type": "application/json"})


def get_valid_domains(soup):

    valid_domains = []
    srcs = soup.findAll(attrs={'src': True})
    hrefs = soup.findAll(attrs={'href': True})

    for i in [urlparse(tag['src']).netloc for tag in srcs]:
        if i != "":
            valid_domains.append(i)

    for i in [urlparse(tag['href']).netloc for tag in hrefs]:
        if i != "":
            valid_domains.append(i)

    return list(sorted(set(valid_domains)))


def is_valid_path(url):
    # Check if the URL points to an image or JS file or GIF or ...
    x = re.search(
        r'\.(css|jpg|jpeg|png|gif|bmp|webp|svg|ico|woff2|js|pdf|xml|txt)$', url, re.IGNORECASE)
    if x:
        return True
    else:
        return False


def is_url(url):

    min_attr = ('scheme', 'netloc')
    try:
        result = urlparse(url)
        if all([result.scheme, result.netloc]):
            return True
        else:
            return False
    except:
        return False


def crawl_paths_to_all_pages(soup, url):
    valid_paths = []
    hrefs = soup.findAll(attrs={'href': True})
    if url[-1] != '/':
        url = url+'/'

    for i in [urlparse(tag['href']).path for tag in hrefs]:
        if i != "":
            if is_url(i):

                if url in i:
                    if not is_valid_path(i):
                        valid_paths.append(i)
            else:
                if not is_valid_path(i):
                    if i[0] != '/':
                        valid_paths.append(url+i)
                    else:
                        valid_paths.append(url+i[1:])

    valid_paths.append(url)

    return list(sorted(set(valid_paths)))


def check_blacklist_in_all_pages(soup, url):

    all_page_paths = crawl_paths_to_all_pages(soup, url)

    alert_words_in_blacklist = ''

    for page in all_page_paths:
        response = requests.get(page)
        soup = BeautifulSoup(response.text, 'html.parser')
        content = soup.get_text()

        for word in BLACKLIST:

            if word in content:
                alert_words_in_blacklist += page + " contains words from BLACKLIST\n"
    return alert_words_in_blacklist


def check_for_change(target_id):

    is_valid_domain = 0
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id, url, last_content , valid_domain FROM targets WHERE id = ?", (target_id,))
    target = cur.fetchone()
    if not target:
        return

    response = requests.get(target[1])
    soup = BeautifulSoup(response.text, 'html.parser')
    valid_domain = target[3].split(' ')

    new_content = soup.get_text()
    new_domains = get_valid_domains(soup)
    print(new_domains)
    for i in new_domains:
        if i not in valid_domain:
            is_valid_domain = 1

    if is_valid_domain:
        send_discord_alert(url=target[1], content="",
                           title="HIGH RISK - UNKNOWN DOMAIN")
    else:
        alert_content_diff = content_diff(target[2], new_content)
        alert_words_in_blacklist = check_blacklist_in_all_pages(
            soup, target[1])

        if alert_content_diff:

            if alert_words_in_blacklist:

                send_discord_alert(url=target[1], content=alert_words_in_blacklist +
                                   alert_content_diff, title="MEDIUM RISK - HAVING WORDS IN BLACKLIST")
            else:
                send_discord_alert(
                    url=target[1], content=alert_content_diff, title="")

        else:
            print(5)
            if alert_words_in_blacklist:
                send_discord_alert(url=target[1], content=alert_words_in_blacklist +
                                   alert_content_diff, title="MEDIUM RISK - HAVING WORDS IN BLACKLIST")


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
        valid_domain = " ".join(get_valid_domains(soup))
        cur.execute("INSERT INTO targets (url,last_content,valid_domain) VALUES (?,?,?)",
                    (url, last_content, valid_domain, ))
        db.commit()
        target_id = cur.lastrowid
        scheduler.add_job(func=check_for_change, trigger="interval",
                          seconds=interval, args=[target_id], id=str(target_id), max_instances=10)
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
