#!/usr/bin/python
# -*- coding: utf-8 -*-

# Ingress Controller Liberty
# Creator: Juan Manuel Torres
# Source: https://github.com/Tedezed
# Mail: juanmanuel.torres@aventurabinaria.es

import datetime
from os import path, getlogin, system, getuid, environ
from elasticsearch import Elasticsearch

class elk_brainslug():

    def __init__(self, kluster):
        self.kluster = kluster
        self.es = Elasticsearch(
            [environ['ELK_HOST']],
            port=environ['ELK_PORT'],
        )

        self.prefix=environ['ELK_PREFIX']
        #self.today = datetime.date.today()
        #self.yesterday = self.today - datetime.timedelta(days=1)
        #self.drop_date = self.today - datetime.timedelta(days=int(environ['ELK_DAYS']))
        #self.index_today="%s-%s" % (self.prefix, self.today.strftime('%Y.%m.%d'))
        #self.index_yesterday="%s-%s" % (self.prefix, self.yesterday.strftime('%Y.%m.%d'))
        #self.drop_index="%s-%s" % (self.prefix, self.drop_date.strftime('%Y.%m.%d'))

    def str_in_list(self, input_str, input_list):
        for i in input_list:
            if i == input_str:
                return True
        return False

    def query_elk_ingress(self, index, ingress_host, file_log):
        #body={"query": { "match": { "ingress": ingress_host }}}
        body={
          "query": {
            "bool": {
              "must": [
                { "match_phrase": { "ingress": ingress_host }},
                { "match_phrase": { "source": file_log }}
              ]
            }
          }
        }
        res = self.es.search(index=index, body=body)
        system("echo 'Query %s %s Score: %s'" % (ingress_host, file_log, res["hits"]["max_score"]))
        if res["hits"]["max_score"]:
            return True
        else:
            return False
        # for r in res['hits']['hits']:
        #     try:
        #         print r["_source"]["ingress"]
        #         print r["_source"]["@timestamp"]
        #     except Exception as e:
        #         pass

    def list_ingress(self):
        ing = self.kluster.extv1beta1.list_ingress_for_all_namespaces(watch=False)
        list_ing = []
        for i in ing.items:
            if i.metadata.annotations:
                if i.metadata.annotations.get('ingress-liberty/start-stop', False) == "true" \
                  and self.str_in_list(i.metadata.annotations.get('kubernetes.io/ingress.class', False), environ['ELK_LIBERTY_NAMES'].split(" ")):
                    list_ing.append(i)
        return list_ing

    # https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/AppsV1beta1Api.md
    # http://docs.clipper.ai/en/v0.3.0/_modules/clipper_admin/kubernetes/kubernetes_container_manager.html
    def replicas_all_namespace(self, replicas, namespace, today):
        system('echo "[INFO] (replicas_all_namespace) namespace: %s time: %s"' % (namespace, today))

        if replicas > 0:
            start_mode=True
            body={
                'metadata': {
                    'annotations': {
                        'ingress-liberty/last-start-stop': today.strftime('%Y.%m.%d')
                    }
                },
                'spec': {
                    'replicas': replicas,
                        }
            }
        else:
            start_mode= False
            body={
                'spec': {
                    'replicas': replicas,
                        }
            }

        deploy = self.kluster.extv1beta1.list_namespaced_deployment(namespace, watch=False)
        for d in deploy.items:
            start_stop=True
            if ((start_mode and int(d.spec.replicas) == 0) or not start_mode):
                if d.metadata.annotations:
                    if d.metadata.annotations.get('ingress-liberty/start-stop', "true") == "false" \
                      or d.metadata.annotations.get('ingress-liberty/last-start-stop', "1983.06.22") == today.strftime('%Y.%m.%d'):
                        start_stop=False
                if start_stop:
                    system('echo "[INFO] Scale to %s deploy: %s"' % (replicas, d.metadata.name))
                    self.kluster.extv1beta1.patch_namespaced_deployment(d.metadata.name, namespace, body)
                else:
                    system('echo "[INFO - %s] start_stop FALSE"' % today)
            else:
                system('echo "[INFO] Deploy in %s without changes"' % namespace)

        rc = self.kluster.v1.list_namespaced_replication_controller(namespace, watch=False)
        for r in rc.items:
            start_stop=True
            if ((start_mode and int(r.spec.replicas) == 0) or not start_mode):
                if r.metadata.annotations:
                    # Ford Orion date: 1983.06.22
                    if r.metadata.annotations.get('ingress-liberty/start-stop', "true") == "false" \
                      or r.metadata.annotations.get('ingress-liberty/last-start-stop', "1983.06.22") == str(today.strftime('%Y.%m.%d')):
                        start_stop=False
                if start_stop:
                    system('echo "[INFO] Scale to %s rc: %s"' % (replicas, r.metadata.name))
                    self.kluster.v1.patch_namespaced_replication_controller(r.metadata.name, namespace, body)
                else:
                    system('echo "[INFO] start_stop FALSE %s"' % today.strftime('%Y.%m.%d'))
            else:
                system('echo "[INFO] RC in %s without changes"' % namespace)

    def stop_ingress(self):
        system('echo "[INFO] ELK Liberty Mode stop"')

        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        drop_date = today - datetime.timedelta(days=int(environ['ELK_DAYS']))
        index_today="%s-%s" % (self.prefix, today.strftime('%Y.%m.%d'))
        index_yesterday="%s-%s" % (self.prefix, yesterday.strftime('%Y.%m.%d'))
        drop_index="%s-%s" % (self.prefix, drop_date.strftime('%Y.%m.%d'))

        system('echo "Drop index: %s"' % drop_index)

        self.es.indices.delete(index=drop_index , ignore=[400, 404])
        list_ing = self.list_ingress()
        for i in list_ing:
            to_stop=True
            for r in i.spec.rules:
                if self.query_elk_ingress(index_yesterday, r.host, "/var/log/nginx/access.log"):
                    to_stop=False
            if to_stop:
                self.replicas_all_namespace(0, i.metadata.namespace, today)
            else:
                system('echo "[INFO] (Query) %s %s without changes"' % (i.metadata.name, i.metadata.namespace))

    def start_ingress(self):
        system('echo "[INFO] ELK Liberty Mode start"')

        today = datetime.datetime.now()
        yesterday = today - datetime.timedelta(days=1)
        drop_date = today - datetime.timedelta(days=int(environ['ELK_DAYS']))
        index_today="%s-%s" % (self.prefix, today.strftime('%Y.%m.%d'))
        index_yesterday="%s-%s" % (self.prefix, yesterday.strftime('%Y.%m.%d'))
        drop_index="%s-%s" % (self.prefix, drop_date.strftime('%Y.%m.%d'))

        list_ing = self.list_ingress()
        for i in list_ing:
            to_start=False
            for r in i.spec.rules:
                if self.query_elk_ingress(index_today, r.host, "/var/log/nginx/custom_error.log"):
                    to_start=True
            if to_start:
                self.replicas_all_namespace(1, i.metadata.namespace, today)
            else:
                system('echo "[INFO] (Query) %s %s without changes"' % (i.metadata.name, i.metadata.namespace))
