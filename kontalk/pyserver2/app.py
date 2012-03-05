# -*- coding: utf-8 -*-
'''Pyserver2 application entry.'''
'''
  Kontalk pyserver2
  Copyright (C) 2011 Kontalk Devteam <devteam@kontalk.org>

 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import logging as log
from Queue import Queue

from twisted.application import internet, service

from version import *
from broker import MessageBroker


class Pyserver2App:
    '''Application starter.'''

    def __init__ (self, argv):
        self.application = service.Application("Pyserver2")

    def setup(self):
        self.print_version()

        self.broker = MessageBroker(self.application)
        self.broker.setup()

        return self.application

    def print_version(self):
        log.info("%s version %s", NAME, VERSION)
