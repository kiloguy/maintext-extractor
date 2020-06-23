import signal
from queue import Queue
from threading import Thread
from time import sleep
from flask import Flask
from flask import jsonify
from flask import request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from sys import exit
from time import time
from math import inf

app = Flask(__name__)

drivers = []
traverseStarts = [0, 0, 0, 0]		# timer for traverse timeout
dq = Queue()	# driver queue (contain driver id), current idle driver

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

for i in range(4):
	drivers.append(webdriver.Chrome(executable_path = '/home/ubuntu/chromedriver', chrome_options = options))
	drivers[i].set_window_size(1920, 1080 * 4)
	print('driver ', i, ' start')

	dq.put(i)

# tags with useful text
allowTags = ['body', 'div', 'article', 'p', 'span', 'code', 'pre', 'p', 'i', 'em', 'strong', 'mark', 'small', 'font',
			 'h1', 'h2', 'h3', 'h4', 'h5', 'a', 'li', 'ol', 'ul', 'br']

def getBaseUrl(url):
    if not url.startswith('https://') and not url.startswith('http://'):
        return ''
    else:
        if url.startswith('https://'):
            if url.find('/', 8) == -1:
                return url
            else:
                return url[:url.find('/', 8)]
        else:	# start with http://
            if url.find('/', 7) == -1:
                return url
            else:
                return url[:url.find('/', 7)]

def crossCenter(rect):
	return rect['x'] < 960 and rect['x'] + rect['width'] > 960

def inCenter(rect):
	x1 = rect['x']
	x2 = rect['x'] + rect['width']

	if x1 < 480:
		if x2 < 480:
			return 0
		elif x2 < 1440:
			return (x2 - 480) / rect['width']
		else:
			return 960 / rect['width']
	elif x1 < 1440:
		if x2 < 1440:
			return 1.0
		else:
			return (1440 - x1) / rect['width']
	else:
		return 0.0

# get y axis of elements (use for sorting)
def yOfElement(elem):
	try:
		return elem.rect['y']
	except:
		return inf

def getPrefix(path, n):
	i = 0
	prefix = ''
	err = False
	while i < n:
		index = path.find('/', len(prefix) + 1)
		if index == -1:
			err = True
			break
		prefix = path[:index]
		i += 1
	if err:
		if i == n - 1:
			return path
		else:
			return ''
	else:
		return prefix

# find same prefix of a list of xpath
def findSamePrefix(paths):
	i = 1
	while True:
		tempPrefix = getPrefix(paths[0], i)
		if tempPrefix == '':
			return getPrefix(paths[0], i - 1)
		for path in paths:
			if getPrefix(path, i) != tempPrefix:
				return getPrefix(path, i - 1)
		i += 1

# get xpath of beautifulsoup node
def getXPath(node):
	path = ''
	while node.name != 'html' :
		pre_same_tag = 0
		has_next_same_tag = False
		for pnode in node.previous_siblings:
			if pnode.name == node.name:
				pre_same_tag += 1
		for nnode in node.next_siblings:
			if nnode.name == node.name:
				has_next_same_tag = True
				break
		if not has_next_same_tag and pre_same_tag == 0:
			path = '/' + node.name + path
		else:
			path = '/' + node.name + '[' + str(pre_same_tag + 1) + ']' + path
		node = node.parent

	path = '/html' + path
	return path

def getNodeText(node):
	s = ''
	for child in node.children:
		if type(child) == NavigableString:
			s += child + ' '
	return s.strip()

# compare function for grouping order
def compare(block1, block2):
	if block1['level'] > block2['level']:
		return 1
	elif block1['level'] < block2['level']:
		return -1
	else:
		if block1['font-size'] > block2['font-size']:
			return 1
		elif block1['font-size'] < block2['font-size']:
			return -1
		else:
			if block1['color'] > block2['color']:
				return 1
			elif block1['color'] < block2['color']:
				return -1
			else:
				if block1['backgroundColor'] > block2['backgroundColor']:
					return 1
				elif block1['backgroundColor'] < block2['backgroundColor']:
					return -1
				else:
					return 0

def insert(block, groups):
	left = 0
	right = len(groups) - 1

	while left <= right:
		mid = left + (right - left) // 2
		res = compare(groups[mid][0], block)
		if res == -1:
			left = mid + 1
		elif res == 1:
			right = mid - 1
		else:
			groups[mid].append(block)
			return
	groups.insert(right + 1, [block])

# traverse and get every node with string child (text node)
def traverse(did, node, level, blocks, groups):
	driver = drivers[did]
	if time() - traverseStarts[did] > 60.0:
		return
	try:
		nodeText = getNodeText(node)
		if nodeText != '' and node.name in allowTags:
			path = getXPath(node)
			try:
				elem = driver.find_element_by_xpath(path)
				# not display node
				if not elem.is_displayed() or elem.rect['width'] * elem.rect['height'] <= 0:
					return
				block = elem.rect.copy()
				block['level'] = level
				block['font-size'] = elem.value_of_css_property('font-size')
				block['color'] = elem.value_of_css_property('color')
				block['backgroundColor'] = elem.value_of_css_property('backgroundColor')
				block['elem'] = elem
				block['xpath'] = path
				blocks.append(block)
				insert(block, groups)
			except:
				pass
		else:
			for child in node.children:
				traverse(did, child, level + 1, blocks, groups)
	except:
		pass

def extractor(url, result):
	startTime = time()
	did = dq.get(True)
	driver = drivers[did]
	driver.get(url)
	print('driver[' + str(did) + '] get ' + url)
	sleep(1)

	soup = BeautifulSoup(driver.page_source, 'html.parser')

	try:
		result['title'] = soup.title.text
	except:
		result['title'] = ''

	# get all links
	result['links'] = []
	links = soup.find_all('a')
	baseUrl = getBaseUrl(url)
	if baseUrl != '':
		for link in links:
			if 'href' in link.attrs:
	    		# generate complete link url
				if link.attrs['href'].startswith('https://') or link.attrs['href'].startswith('http://'):
					result['links'].append(link.attrs['href'])
				elif link.attrs['href'].startswith('/'):
					result['links'].append(baseUrl + link.attrs['href'])
				else:
					result['links'].append(url[:url.rfind('/') + 1] + link.attrs['href'])

	# check article tag first
	if not soup.article is None:
		try:
			maintext = driver.find_element_by_tag_name('article').text
			result['response'] = 'OK'
			result['url'] = url
			result['driver'] = did
			result['maintext'] = maintext
			result['duration'] = time() - startTime
			print('driver[' + str(did) + '] finish task ' + url)
			dq.put(did)
			return
		except:
			pass

	body = soup.body
	blocks = []					# all text element
	groups = []					# group by property of blocks
	abandonElems = []			# elements that should be remove
	tempAcceptPrefixed = []
	finalAcceptElems = []		# final accept element to concat to maintext
	maintext = ''

	traverseStarts[did] = time()
	# traverse to find text blocks(node)
	traverse(did, body, 1, blocks, groups)

	# find each groups' same prefix(parent)
	for group in groups:
		try:
			xpaths = []
			for block in group:
				xpaths.append(block['xpath'])

			prefix = findSamePrefix(xpaths)
			elem = driver.find_element_by_xpath(prefix)
			rect = elem.rect

			if (crossCenter(rect) or inCenter(rect) > 0.9):
				tempAcceptPrefixed.append(prefix)
			else:
				abandonElems.append(elem)
		except:
			pass

	# javascript to remove abandon element
	for path in abandonElems:
		try:
			driver.execute_script("arguments[0].remove();", elem)
		except:
			pass

	tempAcceptPrefixed = list(set(tempAcceptPrefixed))

	# remove element that cover each other in accpet prefix
	temp = tempAcceptPrefixed.copy()
	for i in tempAcceptPrefixed:
		for j in tempAcceptPrefixed:
			if findSamePrefix([i, j]) == i and i != j:
				try:
					temp.remove(j)
				except:
					pass
	tempAcceptPrefixed = temp

	# remove element that too low in y axis
	for path in tempAcceptPrefixed:
		try:
			elem = driver.find_element_by_xpath(path)
			rect = elem.rect
			if rect['y'] < 1080:
				finalAcceptElems.append(elem)
			else:
				driver.execute_script("arguments[0].remove();", elem)
		except:
			pass

	# sort by y axis of final accept elements
	finalAcceptElems.sort(key = yOfElement)

	# concat to make maintext
	for elem in finalAcceptElems:
		try:
			maintext += elem.text + '\n'
		except:
			pass

	result['response'] = 'OK'
	result['url'] = url
	result['driver'] = did
	result['maintext'] = maintext
	result['duration'] = time() - startTime
	print('driver[' + str(did) + '] finish task ' + url)
	dq.put(did)

@app.route('/<path:url>', methods = ['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT', 'OPTIONS', 'TRACE', 'PATCH'])
def extract(url):
	if request.method == 'GET':
		result = {}
		thread = Thread(target = extractor, args = (url, result))
		thread.start()
		thread.join()
		return jsonify(result)
	else:
		return jsonify({'response': 'Error, only support GET request.'})

def serverQuit(signum, frame):
	print(signum)
	for i in range(4):
		drivers[i].quit()
		print('driver ', i, ' quit')
	exit(0)

if __name__ == '__main__':
	signal.signal(signal.SIGINT, serverQuit)
	signal.signal(signal.SIGTERM, serverQuit)
	app.run(host = '0.0.0.0', port = 5001)