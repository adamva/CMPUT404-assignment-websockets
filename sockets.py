#!/usr/bin/env python
# coding: utf-8
# Copyright (c) 2013-2014 Abram Hindle
# Copyright 2023 Adam Ahmed
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import flask
import gevent
import os
import json
import time
from flask import Flask, request, has_request_context, redirect, Response, send_from_directory, url_for
from flask_sockets import Sockets
from gevent import queue

clients = list() # This might be what myWorld.add_listener is for
gevents = list()

def create_app():
    app = Flask(__name__)
    return app

app = create_app()
sockets = Sockets(app)
app.debug = True

def send_all(msg):
    for client in clients:
        client.put( msg )

def send_all_json(obj):
    send_all( json.dumps(obj) )

class Client:
    def __init__(self):
        self.queue = queue.Queue()

    def put(self, v):
        self.queue.put_nowait(v)

    def get(self):
        return self.queue.get()

class World:
    def __init__(self):
        self.clear()
        # we've got listeners now!
        self.listeners = list()
        
    def add_set_listener(self, listener):
        self.listeners.append( listener )

    def update(self, entity, key, value):
        entry = self.space.get(entity,dict())
        entry[key] = value
        self.space[entity] = entry
        self.update_listeners( entity )

    def set(self, entity, data):
        self.space[entity] = data
        self.update_listeners( entity )

    def update_listeners(self, entity):
        '''update the set listeners'''
        for listener in self.listeners:
            listener(entity, self.get(entity))

    def clear(self):
        self.space = dict()

    def get(self, entity):
        return self.space.get(entity,dict())
    
    def world(self):
        return self.space

myWorld = World()        

def set_listener( entity, data ):
    ''' do something with the update ! '''

myWorld.add_set_listener( set_listener )
        
@app.route('/')
def hello():
    '''Redirect to /static/index.html '''
    app.logger.info("Got '/' redirecting to /static/index.html")
    return redirect(url_for('static', filename='index.html'))

def read_ws(ws,client):
    '''A greenlet function that reads from the websocket'''
    try:
        while True:
            msg = ws.receive()
            # print("WS RECV: %s" % msg)
            if (msg is not None):
                packet = json.loads(msg)
                packet_keys = list(packet.keys())
                entity = packet_keys[0]
                data = packet[entity]
                myWorld.set(entity, data)
                send_all_json( packet )
                
            else:
                break
    except:
        '''Done'''

@sockets.route('/subscribe')
def subscribe_socket(ws):
    '''Fufill the websocket URL of /subscribe, every update notify the
       websocket and read updates from the websocket '''
    client = Client()
    # myWorld.add_listenter(client)
    clients.append(client)
    g = gevent.spawn( read_ws, ws, client )    
    print("Subscribing")
    ws.send(json.dumps(myWorld.world()))
    try:
        while True:
            # block here
            msg = client.get()
            # print("Responding with myWorld.world()")
            # print('Responding with ' + msg)
            ws.send(msg)
    except Exception as e:# WebSocketError as e:
        print("WS Error %s" % e)
    finally:
        clients.remove(client)
        gevent.kill(g)


# I give this to you, this is how you get the raw body/data portion of a post in flask
# this should come with flask but whatever, it's not my project.
def flask_post_json():
    '''Ah the joys of frameworks! They do so much work for you
       that they get in the way of sane operation!'''
    if (request.json != None):
        return request.json
    elif (request.data != None and request.data.decode("utf8") != u''):
        return json.loads(request.data.decode("utf8"))
    else:
        return json.loads(request.form.keys()[0])

@app.route("/entity/<entity>", methods=['POST','PUT'])
def update(entity):
    '''Update world entities'''
    response_status = 400
    response_error = {'error': {'code': 1, 'message': 'Could not perform update'}}
    request_post_json = {}
    # Parse incoming request JSON
    try:
        request_post_json = flask_post_json()
    except Exception as e:
        app.logger.error(f'Failed to parse request JSON - [{e}]')
        response_error['error']['code'] = response_status
        response_error['error']['message'] = str(e)
        return Response(response=json.dumps(response_error), status=response_status, mimetype='application/json')
    
    # Update world with request JSON
    did_update = False
    if request.method == 'PUT':
        myWorld.set(entity, request_post_json)
        response_status = 200
        did_update = True
    elif request.method == 'POST':
        for key in request_post_json:
            myWorld.update(entity, key, request_post_json[key])
        response_status = 200
        did_update = True
    else:
        app.logger.error(f'Unknown method [{request.method}]')
        response_status=405

    if did_update:
        new_entity = myWorld.get(entity)
        return Response(response=json.dumps(new_entity), status=response_status, mimetype='application/json')
    else:
        return Response(status=response_status)

@app.route("/world", methods=['POST','GET'])    
def world():
    '''Return the current world'''
    rsp = Response(response=json.dumps(myWorld.world()), status=200, mimetype='application/json')
    return rsp

@app.route("/entity/<entity>")    
def get_entity(entity):
    '''Return the entity from the world'''
    entity_data = myWorld.get(entity)
    if entity_data == {}:
        app.logger.warning(f'Unknown entity [{entity}], returning empty JSON')
    return entity_data

@app.route("/clear", methods=['POST','GET'])
def clear():
    '''Clear the world'''
    myWorld.clear()
    rsp = Response(response=json.dumps(myWorld.world()), status=200, mimetype='application/json')
    return rsp



if __name__ == "__main__":
    ''' This doesn't work well anymore:
        pip install gunicorn
        and run
        gunicorn -k flask_sockets.worker sockets:app
    '''
    app.run(host='0.0.0.0')
