# encoding: utf-8
#
# Copyright (C) 2013 - 2016 Mesar Hameed <mhameed@src.gnome.org>, Beqa gozalishvili
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.

import json
import os
import re
import ssl
import sys
import threading
from random import randint
from time import sleep

import config
import queueHandler
import six
import ui
from logHandler import log

from .configKey import INSTANT_TRANSLATE, SERVICE_NAME

if sys.version_info.major < 3:
	impPath = os.path.abspath(os.path.dirname(__file__))
	sys.path.append(impPath)
	from . import urllib2 as urllibRequest
	from .urllib2 import urlencode

	del sys.path[-1]
else:
	import urllib.request as urllibRequest
	from urllib.parse import urlencode

ssl._create_default_https_context = ssl._create_unverified_context
# Each group has to be a class of possible breaking points for the writing script.
# Usually this is the major syntax marks, such as:
# full stop, comma, exclaim, question, etc.
arabicBreaks = u'[،؛؟]'
# Thanks to Talori in the NVDA irc room:
# U+3000 to U+303F, U+FE10 to U+FE1F, U+FE30 to U+FE6F, U+FF01 to U+FF60
chineseBreaks = u'[　-〿︐-︟︰-﹯！-｠]'
latinBreaks = r'[.,!?;:]'
splitReg = re.compile(
	u"{arabic}|{chinese}|{latin}".format(arabic=arabicBreaks, chinese=chineseBreaks, latin=latinBreaks))


def splitChunks(text, chunksize):
	pos = 0
	potentialPos = 0
	for splitMark in splitReg.finditer(text):
		if (splitMark.start() - pos + 1) < chunksize:
			potentialPos = splitMark.start()
			continue
		else:
			yield text[pos:potentialPos + 1]
			pos = potentialPos + 1
			potentialPos = splitMark.start()
	yield text[pos:]


class GoogleTranslator(threading.Thread):

	def __init__(self, lang_from, lang_to, text, lang_swap=None, chunksize=3000, *args, **kwargs):
		super(GoogleTranslator, self).__init__(*args, **kwargs)
		self._stopEvent = threading.Event()
		self.text = text
		self.chunksize = chunksize
		self.lang_to = lang_to
		self.lang_from = lang_from
		self.lang_swap = lang_swap
		self.translation = ''
		self.lang_detected = ''
		self.opener = urllibRequest.build_opener()
		self.opener.addheaders = [('User-agent', 'Mozilla/5.0')]
		self.firstChunk = True

	def getServiceName():
		return 'Google translator'

	def stop(self):
		self._stopEvent.set()

	def run(self):
		urlTemplate = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl={lang_from}&tl={lang_to}&dt=t&q={text}'
		for chunk in splitChunks(self.text, self.chunksize):
			# Make sure we don't send requests to google too often.
			# Try to simulate a human.
			if not self.firstChunk:
				sleep(randint(1, 10))
			url = urlTemplate.format(lang_from=self.lang_from, lang_to=self.lang_to,
									 text=urllibRequest.quote(chunk.encode('utf-8')))
			try:
				response = json.load(self.opener.open(url))
				if len(response[-1]) > 0:
					# Case where source language is not defined
					temp = response[-1][-1][0]
					# Possible improvement: In case of multiple language detected, there are multiple languages in response[-1][-1].
					self.lang_detected = temp if isinstance(temp, six.text_type) else six.text_type()
					if not self.lang_detected:
						self.lang_detected = _("unavailable")
				else:
					# Case where source language is defined
					self.lang_detected = response[2]
				#				log.info("firstChunk=%s, lang_from=%s, lang_detected=%s, lang_to=%s, lang_swap=%s"%(self.firstChunk, self.lang_from, self.lang_detected, self.lang_to, self.lang_swap))
				if self.firstChunk and self.lang_from == "auto" and self.lang_detected == self.lang_to and self.lang_swap is not None:
					self.lang_to = self.lang_swap
					self.firstChunk = False
					url = urlTemplate.format(lang_from=self.lang_from, lang_to=self.lang_to,
											 text=urllibRequest.quote(chunk.encode('utf-8')))
					response = json.load(self.opener.open(url))
			except Exception as e:
				# We have probably been blocked, so stop trying to translate.
				#				log.exception("Instant translate: Can not translate text '%s'" %chunk)
				#				raise e
				queueHandler.queueFunction(queueHandler.eventQueue, ui.message, _("Translation failed"))
				return
			self.translation += "".join(r[0] for r in response[0])


class YandexTranslator(GoogleTranslator):

	def __init__(self, lang_from, lang_to, text, lang_swap=None, chunksize=3000, *args, **kwargs):
		# yandex doesn't support auto option
		if lang_from == "auto":
			lang_from = self.detect_language(text)
		super().__init__(lang_from, lang_to, text, lang_swap, chunksize, *args, **kwargs)

	def getServiceName():
		return 'Yandex translator'

	def detect_language(self, text):
		response = urllibRequest.urlopen(
			"https://translate.yandex.net/api/v1.5/tr.json/detect?key=trnsl.1.1.20150410T053856Z.1c57628dc3007498.d36b0117d8315e9cab26f8e0302f6055af8132d7&" + urlencode(
				{"text": text.encode('utf-8')})).read()
		response = json.loads(response)
		return response['lang']

	def run(self):
		urlTemplate = 'https://translate.yandex.net/api/v1.5/tr.json/translate?key=trnsl.1.1.20160704T120239Z.5bbe772fede33a6e.f8155753e939ab51790587718370993c40f29897&text={text}&lang={lang_from}-{lang_to}'
		for chunk in splitChunks(self.text, self.chunksize):
			# Make sure we don't send requests to yandex too often.
			# Try to simulate a human.
			if not self.firstChunk:
				sleep(randint(1, 10))
			url = urlTemplate.format(text=urllibRequest.quote(chunk.encode('utf-8')), lang_from=self.lang_from,
									 lang_to=self.lang_to)
			try:
				response = json.load(self.opener.open(url))
				if self.firstChunk and self.lang_from == "auto" and response[
					"src"] == self.lang_to and self.lang_swap is not None:
					self.lang_to = self.lang_swap
					self.firstChunk = False
					url = urlTemplate.format(text=urllibRequest.quote(chunk.encode('utf-8')), lang_from=self.lang_from,
											 lang_to=self.lang_to)
					response = json.load(self.opener.open(url))
			except Exception as e:
				log.exception("Instant translate: Can not translate text '%s'" % chunk)
				# We have probably been blocked, so stop trying to translate.
				raise e
			self.translation += "".join(response['text'])


class TranslatorManager:
	__translators = [
		GoogleTranslator,
		YandexTranslator
	]

	@staticmethod
	def getCurrentTranslator():
		serviceName = config.conf[INSTANT_TRANSLATE].get(SERVICE_NAME)
		for translator in TranslatorManager.__translators:
			if translator.getServiceName() == serviceName:
				return translator
		return GoogleTranslator

	@staticmethod
	def setNextTranslator():
		currentIndex = TranslatorManager.__translators \
			.index(TranslatorManager.getCurrentTranslator())
		nextIndex = currentIndex + 1
		if nextIndex == len(TranslatorManager.__translators):
			nextIndex = 0
		translator = TranslatorManager.__translators[nextIndex]
		config.conf[INSTANT_TRANSLATE][SERVICE_NAME] = translator.getServiceName()
