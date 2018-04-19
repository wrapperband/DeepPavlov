"""
Copyright 2017 Neural Networks and Deep Learning lab, MIPT

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import collections
import numpy as np

from deeppavlov.core.models.component import Component
from deeppavlov.core.common.registry import register
from deeppavlov.core.common.log import get_logger


log = get_logger(__name__)


@register('kg_manager')
class KudaGoDialogueManager(Component):
    def __init__(self, cluster_policy, min_num_events, *args, **kwargs):
        self.cluster_policy = cluster_policy
        self.min_num_events = min_num_events

    def __call__(self, events, slots, utter_history):
        messages, cluster_ids = [], []
        for events, slots, utter_history in zip(events, slots, utter_history):
            if len(events) < self.min_num_events:
                log.debug("Number of events = {} < {}"
                          .format(len(events), self.min_num_events))
                messages.append(events)
                cluster_ids.append(None)
            else:
                message, cluster_id = self.cluster_policy([events])
                message, cluster_id = message[0], cluster_id[0]
                if cluster_id is None:
                    log.debug("Cluster policy didn't work: cluster_id = None")
                    messages.append(events)
                    cluster_ids.append(None)
                else:
                    log.debug("Requiring cluster_id = {}".format(cluster_id))
                    messages.append(message)
                    cluster_ids.append(cluster_id)
        return messages, cluster_ids


@register('kg_cluster_policy')
class KudaGoClusterPolicyManager(Component):
    def __init__(self, data, tags=None, min_rate=0.01, max_rate=0.99, *args, **kwargs):
        clusters = {cl_id: cl for cl_id, cl in data['slots'].items()
                    if cl['type'] == 'ClusterSlot'}
        self.questions_d = {cl_id: cl['questions'] for cl_id, cl in clusters.items()}
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.tags_l = tags

        if self.tags_l is None:
            self.tags_l = list(set(t for cl in clusters.values() for t in cl['tags']))
        # clusters: (num_clusters, num_tags)
        self.clusters_oh = {cl_id: self._onehot([cl['tags']], self.tags_l)
                            for cl_id, cl in clusters.items()}

    @staticmethod
    def _onehot(tags, all_tags):
        """
        tags: list of lists of str tags
        all_tags: list of str tags
        Returns:
            np.array (num_samples, num_tags)
        """
        num_samples, num_tags = len(tags), len(all_tags)
        onehoted = np.zeros((num_samples, num_tags))
        for i, s_tags in enumerate(tags):
            s_filtered_tags = set.intersection(set(s_tags), set(all_tags))
            for t in s_filtered_tags:
                onehoted[i, all_tags.index(t)] = 1
        return onehoted

    def __call__(self, events):
#TODO: support slot_history
        questions, cluster_ids = [], []
        for events_l in events:
            event_tags_l = [e['tags'] for e in events_l if e['tags']]
            event_tags_oh = self._onehot(event_tags_l, self.tags_l)

            bst_cluster_id, bst_rate = self._best_divide(event_tags_oh)
            log.debug("best tag split with cluster_id = {} and rate = {}"
                      .format(bst_cluster_id, bst_rate))
            if (bst_rate < self.min_rate) or (bst_rate > self.max_rate):
                questions.append("")
                cluster_ids.append(None)
            else:
                questions.append(self.questions_d[bst_cluster_id])
                cluster_ids.append(bst_cluster_id)
        return questions, cluster_ids

    def _best_divide(self, event_tags_oh):
        """
        event_tags_oh: np.array (num_samples, num_tags)
        Returns: 
            cluster_id: str,
            divide_rate: float
        """
        cluster_ids = []
        split_rates = []
        num_events = self._num_events_with_tags(event_tags_oh)
        for cl_id, cl_oh in self.clusters_oh.items():
            cluster_ids.append(cl_id)
            split_event_tags_oh = self._split_by_tags(event_tags_oh, cl_oh)
            num_split_events = self._num_events_with_tags(split_event_tags_oh)
            split_rates.append(num_split_events / num_events)
        best_idx = np.argmin(np.fabs(0.5 - np.array(split_rates)))
        return cluster_ids[best_idx], split_rates[best_idx]

    @staticmethod
    def _split_by_tags(event_tags_oh, tags_oh):
        """
        event_tags_oh: np.array (num_samples x num_tags)
        tags_oh: np.array (num_tags x 1) or (num_tags)
        Returns:
            np.array (num_samples x num_tags)
        """
        return np.multiply(event_tags_oh, tags_oh)

    @staticmethod
    def _num_events_with_tags(event_tags_oh):
        """
        event_tags_oh: np.array (num_samples x num_tags)
        Returns:
            int
        """
        return np.sum(np.sum(event_tags_oh, axis=1) > 0)
