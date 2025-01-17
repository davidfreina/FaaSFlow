from gevent import monkey
monkey.patch_all()
import uuid
import requests
import getopt
import sys
sys.path.append('..')
sys.path.append('../../../config')
from repository import Repository
import config
import pandas as pd
import gevent

repo = Repository()
latencies = []
ticket = 0
running = 0
timeout = 0
BANDWIDTH = 50
TEST_PER_WORKFLOW = 2 * 60
RPM = 0
workflow = ''

def run_workflow(workflow_name, request_id):
    print('----firing workflow----', request_id)
    global latencies, ticket, running, timeout
    ticket = ticket - 1
    running = running + 1
    if ticket > 0 and timeout < 3:
        gevent.spawn_later(60 / RPM, run_workflow, workflow_name, str(uuid.uuid4()))
    url = 'http://' + config.GATEWAY_ADDR + '/run'
    data = {"workflow":workflow_name, "request_id": request_id}
    try:
        rep = requests.post(url, json=data, timeout=60)
        e2e_latency = rep.json()['latency']
        latencies.append(e2e_latency)
        print('e2e latency: ', e2e_latency)
    except Exception:
        print(f'{workflow_name} timeout')
        timeout = timeout + 1
    running = running - 1

def analyze_workflow():
    global latencies, timeout
    if timeout >= 3:
        return 'timeout'
    latencies.sort()
    if len(latencies) < 100:
        return latencies[-1]
    else:
        tail = int(len(latencies) / 100)
        return latencies[-tail]

def analyze(datamode, workflow):
    global BANDWIDTH, ticket, running, timeout, latencies, RPM
    tail_latencies = []
    for rpm in config.RPMs[f'{workflow}-{BANDWIDTH}']:
        RPM = rpm
        print(f'----analyzing {workflow} at bandwidth {BANDWIDTH}MB/s, {rpm}RPM, prewarming----')

        # prewarm to achieve stable throughput
        ticket = 2
        running = 0
        timeout = 0
        gevent.spawn(run_workflow, workflow, str(uuid.uuid4()))
        gevent.sleep(5)
        while True:
            if running == 0 and timeout != 0: # timeout
                break
            if ticket == 0 and running == 0: # finished running
                break
            gevent.sleep(5)
        if timeout == 2:
            tail_latencies.append('timeout')
            break

        # tail latency analysis
        ticket = RPM * TEST_PER_WORKFLOW / 60
        running = 0
        timeout = 0
        latencies = []
        gevent.spawn(run_workflow, workflow, str(uuid.uuid4()))
        gevent.sleep(5)
        while True:
            if running == 0 and timeout != 0: # timeout
                break
            if ticket == 0 and running == 0: # finished running
                break
            gevent.sleep(5)
        if timeout != 0:
            tail_latencies.append('timeout')
            break
        tail_latency = analyze_workflow()
        print(f'{workflow} tail latency: {tail_latency}')
        tail_latencies.append(tail_latency)
    for _ in range(len(config.RPMs[f'{workflow}-{BANDWIDTH}']) - len(tail_latencies)):
        tail_latencies.append('timeout')
    df = pd.DataFrame({'rpm': config.RPMs[f'{workflow}-{BANDWIDTH}'], 'tail_latency': tail_latencies})
    df.to_csv(f'{datamode}_{workflow}_{BANDWIDTH}MB.csv')

if __name__ == '__main__':
    repo.clear_couchdb_results()
    repo.clear_couchdb_workflow_latency()
    opts, args = getopt.getopt(sys.argv[1:],'',['bandwidth=', 'datamode=', 'workflow='])
    for name, value in opts:
        if name == '--bandwidth':
            BANDWIDTH = value
        elif name == '--datamode':
            datamode = value
        elif name == '--workflow':
            workflow = value
    analyze(datamode, workflow)
