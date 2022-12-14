#!/usr/bin/env python3

import sys
import redis
#sys.path.append("./dnspython")
# sys.path.append("./dnslib")
# sys.path.append("./python-daemon")
# sys.path.append("./pylockfile")
from dns import message, query, exception
#from dns import rdatatype, resolver
import time
#import multiprocessing.pool
import socket
import http.client
import argparse
import datetime
import threading
import traceback
import socketserver
import dnslib
import os.path
import signal
# import daemon
# import daemon.pidfile
import logging
import pickle
import queue as Queue
from threading import Thread
#from dnslib import *


# Constants
# http://pcsupport.about.com/od/tipstricks/a/free-public-dns-servers.htm
# http://www.tech-faq.com/public-dns-servers.html
# http://www.bestdns.org/
# '223.5.5.5'
DNSlist = ['128.2.184.224', '8.8.8.8', '9.9.9.9', '208.67.222.222', '209.244.0.3',\
           '8.26.56.26', '74.82.42.42', '151.197.0.38']
# DNSlist = ['128.2.184.224']
PORT = 53

PIDFILE = os.path.abspath(r'./server.pid')
# CACHE_FILE = os.path.abspath(r"./cache.db")

# the record cache
cache = {}
# the worker threads


class FetchWorker(Thread):
    def __init__(self, dns_index_req):
        Thread.__init__(self)
        self.dns_index_req = dns_index_req

    def run(self):
        dns_index_req = self.dns_index_req
        dns_index = dns_index_req[0]
        domain = dns_index_req[1]
        query_type = dns_index_req[2]
        queue = dns_index_req[3]
        request = dns_index_req[4]
        q = message.make_query(domain, query_type)
        q.id = request.header.id
        rcode = q.rcode()
        count = 0
        start = time.time()*1000
        while True and count < 3:
            try:
                msg = query.udp(q, DNSlist[dns_index], timeout=1) 
            except exception.Timeout:
                count += 1
                continue
            break
        if count >= 3:
            logging.warning("Worker thread %d too many retries", dns_index)
            queue.put(([], rcode))
            return rcode
        ips = []
        answer = None
        logging.debug("Worker thread %d gets reply %s", dns_index, msg.answer)
        for anss in msg.answer:
            #print "Type", rdatatype.to_text(anss.to_rdataset().rdtype)
            if anss.to_rdataset().rdtype == query_type: #match record type
            #    logging.debug("reply %s", anss)
                answer = anss
        if answer is None:
            logging.warning("Worker thread %d empty response for %s",\
                            dns_index, domain)
            queue.put(([], rcode))
            return 1
        for ans in answer:
            ips.append(ans.to_text())
        end = time.time()*1000
        logging.debug("Worker thread %d got answer, delay: %dms",
                      dns_index, end-start)
        queue.put((ips, rcode))
        #time.sleep(0)
        return 0

def merge_duplicated(answers, qtype):
    prefix_pool = {}
    ip_list = []
    for ans in answers:
        for a in ans[0]:
            if '.'.join(a.split(".")[:3]) not in prefix_pool:
                #ignore the IP from same subnet
                ip_list.append(a)
                prefix_pool['.'.join(a.split(".")[:3])] = 1
            else:
                pass
    return ip_list


def round_trip_latency(IP):

    start = time.time()*1000
    h1 = http.client.HTTPConnection(IP)
    try:
        h1.connect()
    except socket.timeout:
        return 9999
    end = time.time()*1000
    h1.close()
    return end - start

def refine(qname_str, qtype, answers):
    logging.info('refining answers for %s', qname_str)
    if qtype != dnslib.QTYPE.A:
        # only cache the results from the first success resolver
        for ans in answers:
            if ans[1] == 0:
                cache[(qname_str, qtype)] = ans
                break
        return
    IPs = merge_duplicated(answers, qtype)
    logging.debug('reduce to %s', IPs)

    min_RTT = 9999
    min_IP = IPs[0]

    if len(IPs) > 1:
        for IP in IPs:
            rtt = round_trip_latency(IP)
            logging.debug('RTT: %s, %s', IP, rtt)
            if rtt < min_RTT:
                min_RTT = rtt
                min_IP = IP
    logging.info('min IP: %s', min_IP)
    cache[(qname_str, qtype)] = ([min_IP], 0)


def parallel_resolve(request, reply_callback, qname_str=None, qtype=None):
    # if request and reply_callback are set, this function is called for a query
    # otherwise qname_str and qtype are set, this function is called to refresh
    logging.debug("Parallel resolver")
    start = time.time()*1000
    if request:
        qname_str = str(request.q.qname)
        qtype = request.q.qtype

    queue = Queue.Queue()

    # Fire parallel lookups
    flag = []

    workers = []
    for i in range(len(DNSlist)):
        worker = FetchWorker((i, qname_str, qtype, queue, request,
                              reply_callback, flag))
        worker.daemon = True
        worker.start()
        workers.append(worker)

    end = time.time()*1000
    logging.debug("prepare task, latency: %d ms", (end-start))
    time.sleep(0)
    # get the first response, and reply to client
    #logging.debug("waiting for first response")
    #start = time.time()*1000
    #first_response = queue.get()

    #end = time.time()*1000
    #print "parallel_resolve, latency: %d ms"%(end-start)
    #logging.info("got first response:%s, replying", first_response)
    #start = time.time()*1000
    #if reply_callback:
    #    reply_query(first_response, request, reply_callback)
    #end = time.time()*1000
    #print "Send reply, latency: %d ms"%(end-start)
    # wait for the rest answers
    #answers = [first_response]
    answers = []

    for worker in workers:
        worker.join()
    logging.debug("all workers finished")
    while not queue.empty():
        answers.append(queue.get())

    refine(qname_str, qtype, answers)


def dns_resolve(request, reply_callback):
    logging.debug("resolving")
    qname_str = str(request.q.qname)
    qtype = request.q.qtype
    if (qname_str, qtype) in cache:
        # cache hit
        logging.info("cache hit: %s", qname_str)
        answer = cache[(qname_str, qtype)]
        reply_query(answer, request, reply_callback)
    else:
        # cache miss, query DNS resolvers
        parallel_resolve(request, reply_callback)


def reply_query(answer, request, reply_callback):
    DNS_response = prepare_reply(answer, request)
    reply_callback(DNS_response)


def prepare_reply(answer, request):
    #pack anwsers
    qname = request.q.qname
    qtype = request.q.qtype
    qt = dnslib.QTYPE[qtype]
    rcode = 0

    reply = dnslib.DNSRecord(\
                dnslib.DNSHeader(id=request.header.id, qr=1, aa=1, ra=1),\
                                 q=request.q)
    bad_reply = dnslib.DNSRecord(dnslib.DNSHeader(\
                            id=request.header.id, qr=1, aa=1, ra=1,\
                            rcode=rcode), q=request.q)

    record_class = getattr(dnslib, str(qt))
    empty_ans = True
    if rcode == 0:
        rcode = answer[1]
    for a in answer[0]:
        empty_ans = False
        reply.add_answer(dnslib.RR(rname=qname, rtype=qtype,\
                     rclass=1, ttl=10, rdata=record_class(a)))

    #print "---- Reply:\n", reply
    # if failed, send back error code
    if empty_ans and rcode > 0:
        reply = bad_reply

    return reply.pack()

def process_DNS_query(data, reply_callback):
    logging.debug("parsing DNS query")
    # parse the request
    request = dnslib.DNSRecord.parse(data)
    logging.info('Lookup request: %s', request)
    # lookup the record
    dns_resolve(request, reply_callback)



class BaseRequestHandler(socketserver.BaseRequestHandler):

    def get_data(self):
        raise NotImplementedError

    def send_data(self, data):
        raise NotImplementedError

    def handle(self):
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')
        logging.info('Got request: \n\n%s request %s (%s %s):',\
                     self.__class__.__name__[:3],\
                     now, self.client_address[0], self.client_address[1])
        try:
            data = self.get_data()
            # print(data,type(data))
            logging.debug('RAW data(%d): %s', len(data), data.hex())
            # repr(data).replace('\\x', '')[1:-1]
            process_DNS_query(data, self.send_data)
            #self.send_data(dns_response(data))
        except Exception:
            traceback.print_exc(file=sys.stderr)


class TCPRequestHandler(BaseRequestHandler):

    def get_data(self):
        data = self.request.recv(8192)
        sz = int(data[:2].encode('hex'), 16)
        if sz < len(data) - 2:
            raise Exception("Wrong size of TCP packet")
        elif sz > len(data) - 2:
            raise Exception("Too big TCP packet")
        return data[2:]

    def send_data(self, data):
        sz = hex(len(data))[2:].zfill(4).decode('hex')
        return self.request.sendall(sz + data)


class UDPRequestHandler(BaseRequestHandler):

    def get_data(self):
        return self.request[0]

    def send_data(self, data):
        return self.request[1].sendto(data, self.client_address)

def cache_manager():
    # reload cache saved to disk
    r = redis.Redis(host='localhost',port=6379, db=0)
    # if os.path.isfile(CACHE_FILE):
    #     with open(CACHE_FILE, 'rb') as f:
    #         file_cache = pickle.load(f)
    #         for k in file_cache:
    #             cache[k] = file_cache[k]
    #     logging.info('Loaded %d cache entries from disk', len(cache))

    while True:
        for k in r.keys():
            cache[k] = r.get(k)
        logging.info('load %d cache entries from redis', len(cache))
        time.sleep(20)
        print(cache)
        for k,v in cache.items():
            logging.info(111, k, v)
            r.set(k, v)
        # with open(CACHE_FILE, 'wb+') as f:
        #     pickle.dump(cache, f)
        logging.info('Autosaved %d cache entries to redis', len(cache))



def start_server(port=PORT):
    logging.info("Starting nameserver...")

    servers = [
        socketserver.ThreadingUDPServer(('127.0.0.1', port), UDPRequestHandler),
        socketserver.ThreadingTCPServer(('127.0.0.1', port), TCPRequestHandler),
    ]
    routines = [
        threading.Thread(name='CacheManager', target=cache_manager, args=())
    ]

    for s in servers:
        thread = threading.Thread(target=s.serve_forever)
         # that thread will start one more thread for each request
        thread.daemon = True
        # exit the server thread when the main thread terminates
        thread.start()
        logging.info("%s server loop running in thread: %s",\
                     s.RequestHandlerClass.__name__[:3], thread.name)
    for r in routines:
        r.daemon = True
        r.start()
        logging.info("Routine %s started", r.name)

    try:
        while 1:
            time.sleep(1)
            sys.stderr.flush()
            sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        logging.warning('Shutting down servers')
        for s in servers:
            s.shutdown()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(\
                formatter_class=argparse.ArgumentDefaultsHelpFormatter,\
                description='very fast DNS resolver')
    parser.add_argument('-p', '--port', type=int, default=53,\
                        help='the TCP port number the agent listens')
    parser.add_argument('-d', '--daemon', action='store_true', default=False,\
                        help='run the agent as a daemon')
    parser.add_argument('-k', '--kill', action='store_true', default=False,\
                        help='kill a running daemon')
    parser.add_argument('-q', '--quiet', action='store_true', default=False,\
                        help='only print errors')
    parser.add_argument('-v', '--verbose', action='store_true', default=False,\
                        help='print debug info.')
    args = parser.parse_args()
    if args.quiet:
        level = logging.WARNING
    elif args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(
        format="%(levelname) -10s %(asctime)s\
                %(threadName)s:%(lineno) -7s %(message)s",
        level=level
    )

    if args.daemon:
        pidFile = daemon.pidfile.PIDLockFile(PIDFILE)
        pid = pidFile.read_pid()
        if pid is not None:
            logging.critical("Another daemon, PID %d, is running. Quit.", pid)
            sys.exit(-1)
        serverLog = open('log.log', 'a+')
        context = daemon.DaemonContext(stdout=serverLog,
                                       stderr=serverLog,
                                       pidfile=pidFile)
        context.files_preserve = [serverLog]
        with context:
            logging.info("Starting Daemon on port %d", args.port)
            start_server(port=args.port)
    elif args.kill:
        pidFile = daemon.pidfile.PIDLockFile(PIDFILE)
        pid = pidFile.read_pid()
        if pid is None:
            logging.error("No daemon found.")
            sys.exit(-1)
        else:
            os.kill(int(pid), signal.SIGINT)
            logging.info("PID %d killed", pid)

    else:
        start_server(port=args.port)
