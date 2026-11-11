import requests
from bs4 import BeautifulSoup

def route_competitor(url):
    soup = BeautifulSoup(requests.get(url, timeout=20, headers={'User-Agent': 'research-bot'}).text, 'html.parser')
    return [(p.select_one('.name').text.strip(), p.select_one('.price').text.strip()) for p in soup.select('.product')]
