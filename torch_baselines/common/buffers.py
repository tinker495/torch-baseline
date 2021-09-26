import random
from typing import Optional, List, Union

import numpy as np

from torch_baselines.common.segment_tree import SumSegmentTree, MinSegmentTree


class ReplayBuffer(object):
    def __init__(self, size: int):
        """
        Implements a ring buffer (FIFO).

        :param size: (int)  Max number of transitions to store in the buffer. When the buffer overflows the old
            memories are dropped.
        """
        self._storage = []
        self._maxsize = size
        self._next_idx = 0

    def __len__(self) -> int:
        return len(self._storage)

    @property
    def storage(self):
        """[(Union[np.ndarray, int], Union[np.ndarray, int], float, Union[np.ndarray, int], bool)]: content of the replay buffer"""
        return self._storage

    @property
    def buffer_size(self) -> int:
        """float: Max capacity of the buffer"""
        return self._maxsize

    def can_sample(self, n_samples: int) -> bool:
        """
        Check if n_samples samples can be sampled
        from the buffer.

        :param n_samples: (int)
        :return: (bool)
        """
        return len(self) >= n_samples

    def is_full(self) -> int:
        """
        Check whether the replay buffer is full or not.

        :return: (bool)
        """
        return len(self) == self.buffer_size

    def add(self, obs_t, action, reward, nxtobs_t, done):
        """
        add a new transition to the buffer

        :param obs_t: (Union[np.ndarray, int]) the last observation
        :param action: (Union[np.ndarray, int]) the action
        :param reward: (float) the reward of the transition
        :param obs_tp1: (Union[np.ndarray, int]) the current observation
        :param done: (bool) is the episode done
        """
        data = (obs_t, action, reward, nxtobs_t, done)

        if self._next_idx >= len(self._storage):
            self._storage.append(data)
        else:
            self._storage[self._next_idx] = data
        self._next_idx = (self._next_idx + 1) % self._maxsize

    def _encode_sample(self, idxes: Union[List[int], np.ndarray]):
        obses_t, actions, rewards, nxtobses_t, dones = [], [], [], [], []
        for i in idxes:
            data = self._storage[i]
            obs_t, action, reward, nxtobs_t, done = data
            obses_t.append(obs_t)
            actions.append(action)
            rewards.append(reward)
            nxtobses_t.append(nxtobs_t)
            dones.append(done)
        obses_t = [np.array(o) for o in list(zip(*obses_t))]
        actions = np.array(actions)
        rewards = np.array(rewards)
        nxtobses_t = [np.array(no) for no in list(zip(*nxtobses_t))]
        dones = np.array(dones)
        return (obses_t,
                actions,
                rewards,
                nxtobses_t,
                dones)

    def sample(self, batch_size: int):
        """
        Sample a batch of experiences.

        :param batch_size: (int) How many transitions to sample.
        :param env: (Optional[VecNormalize]) associated gym VecEnv
            to normalize the observations/rewards when sampling
        :return:
            - obs_batch: (np.ndarray) batch of observations
            - act_batch: (numpy float) batch of actions executed given obs_batch
            - rew_batch: (numpy float) rewards received as results of executing act_batch
            - next_obs_batch: (np.ndarray) next set of observations seen after executing act_batch
            - done_mask: (numpy bool) done_mask[i] = 1 if executing act_batch[i] resulted in the end of an episode
                and 0 otherwise.
        """
        idxes = [random.randint(0, len(self._storage) - 1) for _ in range(batch_size)]
        return self._encode_sample(idxes)

class EfficentReplayBuffer(object):
    def __init__(self, size: int, observation_space: list):
        """
        Implements a ring buffer (FIFO).

        :param size: (int)  Max number of transitions to store in the buffer. When the buffer overflows the old
            memories are dropped.
        """
        self.observation_space = [[o[1],o[2],o[0]] if len(o) == 3 else o for o in observation_space]
        self.obs_num = len(observation_space)
        self.observation_storage = [np.zeros([size]+obspace) for obspace in observation_space]
        self.next_observation_storage = [np.zeros([size]+obspace) for obspace in observation_space]
        self.action_storage = np.zeros([size])
        self.reward_storage = np.zeros([size])
        self.done_storage = np.zeros([size])
        self._maxsize = size
        self._next_idx = 0
        self.storage_size = 0

    def __len__(self) -> int:
        return self.storage_size

    @property
    def storage(self):
        """[(Union[np.ndarray, int], Union[np.ndarray, int], float, Union[np.ndarray, int], bool)]: content of the replay buffer"""
        return (self.observation_storage,self.action_storage,self.reward_storage,self.next_observation_storage,self.done_storage)

    @property
    def buffer_size(self) -> int:
        """float: Max capacity of the buffer"""
        return self._maxsize

    def can_sample(self, n_samples: int) -> bool:
        """
        Check if n_samples samples can be sampled
        from the buffer.

        :param n_samples: (int)
        :return: (bool)
        """
        return len(self) >= n_samples

    def add(self, obs_t, action, reward, nxtobs_t, done):
        """
        add a new transition to the buffer

        :param obs_t: (Union[np.ndarray, int]) the last observation
        :param action: (Union[np.ndarray, int]) the action
        :param reward: (float) the reward of the transition
        :param obs_tp1: (Union[np.ndarray, int]) the current observation
        :param done: (bool) is the episode done
        """
        for ob in np.arange(self.obs_num):
            self.observation_storage[ob][self._next_idx] = obs_t[ob]
            self.next_observation_storage[ob][self._next_idx] = nxtobs_t[ob]
        self.action_storage[self._next_idx] = action
        self.reward_storage[self._next_idx] = reward
        self.done_storage[self._next_idx] = done
        self._next_idx = (self._next_idx + 1) % self._maxsize
        if self.storage_size < self._maxsize:
            self.storage_size += 1

    def _encode_sample(self, idxes: Union[List[int], np.ndarray]):
        obses_t = []
        nxtobses_t = []
        for ob in np.arange(self.obs_num):
            obses_t.append = self.observation_storage[ob][idxes]
            nxtobses_t.append = self.next_observation_storage[ob][idxes]
        actions = self.action_storage[idxes]
        rewards = self.reward_storage[idxes]
        dones = self.done_storage[idxes]
        return (obses_t,
                actions,
                rewards,
                nxtobses_t,
                dones)

    def sample(self, batch_size: int):
        """
        Sample a batch of experiences.

        :param batch_size: (int) How many transitions to sample.
        :param env: (Optional[VecNormalize]) associated gym VecEnv
            to normalize the observations/rewards when sampling
        :return:
            - obs_batch: (np.ndarray) batch of observations
            - act_batch: (numpy float) batch of actions executed given obs_batch
            - rew_batch: (numpy float) rewards received as results of executing act_batch
            - next_obs_batch: (np.ndarray) next set of observations seen after executing act_batch
            - done_mask: (numpy bool) done_mask[i] = 1 if executing act_batch[i] resulted in the end of an episode
                and 0 otherwise.
        """
        idxes = np.random.randint(0,self.storage_size - 1,size=batch_size) #[random.randint(0, self.storage_size - 1) for _ in range(batch_size)]
        return self._encode_sample(idxes)

class PrioritizedReplayBuffer(ReplayBuffer):
    def __init__(self, size, alpha):
        """
        Create Prioritized Replay buffer.

        See Also ReplayBuffer.__init__

        :param size: (int) Max number of transitions to store in the buffer. When the buffer overflows the old memories
            are dropped.
        :param alpha: (float) how much prioritization is used (0 - no prioritization, 1 - full prioritization)
        """
        super(PrioritizedReplayBuffer, self).__init__(size)
        assert alpha >= 0
        self._alpha = alpha

        it_capacity = 1
        while it_capacity < size:
            it_capacity *= 2

        self._it_sum = SumSegmentTree(it_capacity)
        self._it_min = MinSegmentTree(it_capacity)
        self._max_priority = 1.0

    def add(self, obs_t, action, reward, nxtobs_t, done):
        """
        add a new transition to the buffer

        :param obs_t: (Any) the last observation
        :param action: ([float]) the action
        :param reward: (float) the reward of the transition
        :param obs_tp1: (Any) the current observation
        :param done: (bool) is the episode done
        """
        idx = self._next_idx
        super().add(obs_t, action, reward, nxtobs_t, done)
        self._it_sum[idx] = self._max_priority ** self._alpha
        self._it_min[idx] = self._max_priority ** self._alpha

    def _sample_proportional(self, batch_size):
        mass = []
        total = self._it_sum.sum(0, len(self._storage) - 1)
        # TODO(szymon): should we ensure no repeats?
        mass = np.random.random(size=batch_size) * total
        idx = np.array(self._it_sum.find_prefixsum_idx(mass))
        return idx

    def sample(self, batch_size: int, beta: float = 0):
        """
        Sample a batch of experiences.

        compared to ReplayBuffer.sample
        it also returns importance weights and idxes
        of sampled experiences.

        :param batch_size: (int) How many transitions to sample.
        :param beta: (float) To what degree to use importance weights (0 - no corrections, 1 - full correction)
        :param env: (Optional[VecNormalize]) associated gym VecEnv
            to normalize the observations/rewards when sampling
        :return:
            - obs_batch: (np.ndarray) batch of observations
            - act_batch: (numpy float) batch of actions executed given obs_batch
            - rew_batch: (numpy float) rewards received as results of executing act_batch
            - next_obs_batch: (np.ndarray) next set of observations seen after executing act_batch
            - done_mask: (numpy bool) done_mask[i] = 1 if executing act_batch[i] resulted in the end of an episode
                and 0 otherwise.
            - weights: (numpy float) Array of shape (batch_size,) and dtype np.float32 denoting importance weight of
                each sampled transition
            - idxes: (numpy int) Array of shape (batch_size,) and dtype np.int32 idexes in buffer of sampled experiences
        """
        assert beta > 0

        idxes = self._sample_proportional(batch_size)
        weights = []
        p_min = self._it_min.min() / self._it_sum.sum()
        max_weight = (p_min * len(self._storage)) ** (-beta)
        p_sample = self._it_sum[idxes] / self._it_sum.sum()
        weights = np.array((p_sample * len(self._storage)) ** (-beta) / max_weight)
        encoded_sample = self._encode_sample(idxes)
        return encoded_sample + (weights, idxes)

    def update_priorities(self, idxes, priorities):
        """
        Update priorities of sampled transitions.

        sets priority of transition at index idxes[i] in buffer
        to priorities[i].

        :param idxes: ([int]) List of idxes of sampled transitions
        :param priorities: ([float]) List of updated priorities corresponding to transitions at the sampled idxes
            denoted by variable `idxes`.
        """
        assert len(idxes) == len(priorities)
        assert np.min(priorities) > 0
        assert np.min(idxes) >= 0
        assert np.max(idxes) < len(self.storage)
        self._it_sum[idxes] = priorities ** self._alpha
        self._it_min[idxes] = priorities ** self._alpha

        self._max_priority = max(self._max_priority, np.max(priorities))*0.95
        
class EpisodicReplayBuffer(ReplayBuffer):
    def __init__(self, size, worker_size, n_step, gamma):
        """
        Create Episodic Replay buffer for n-step td

        See Also ReplayBuffer.__init__

        :param size: (int) Max number of transitions to store in the buffer. When the buffer overflows the old memories
            are dropped.
        :param alpha: (float) how much prioritization is used (0 - no prioritization, 1 - full prioritization)
        """
        super(EpisodicReplayBuffer, self).__init__(size)
        self.episodes = {}
        self.worker_ep = np.zeros(worker_size)
        self.n_step = n_step
        self.gamma = gamma
        
    def add(self, obs_t, action, reward, nxtobs_t, done, worker, terminal):
        """
        add a new transition to the buffer

        :param obs_t: (Any) the last observation
        :param action: ([float]) the action
        :param reward: (float) the reward of the transition
        :param obs_tp1: (Any) the current observation
        :param done: (bool) is the episode done
        """
        episode_key = (worker,self.worker_ep[worker])
        if episode_key not in self.episodes:
            self.episodes[episode_key] = []
        self.episodes[episode_key].append(self._next_idx)
        data = (obs_t, action, reward, nxtobs_t, done, (episode_key,len(self.episodes[episode_key])), terminal)
        if self._next_idx >= len(self._storage):
            self._storage.append(data)
        else:
            if self._storage[self._next_idx][6]: #remove episode data when remove last episode from storage
                del self.episodes[self._storage[self._next_idx][5][0]]
            self._storage[self._next_idx] = data
        self._next_idx = (self._next_idx + 1) % self._maxsize
        if terminal:
            self.worker_ep[worker] += 1

    def _encode_sample(self, idxes: Union[List[int], np.ndarray]):
        obses_t, actions, rewards, nxtobses_t, dones = [], [], [], [], []
        for i in idxes:
            data = self._storage[i]
            obs_t, action, reward, nxtobs_t, done, episode_key_and_idx, _ = data
            episode_key, episode_index = episode_key_and_idx
            nstep_idxs = self.episodes[episode_key][episode_index:(episode_index+self.n_step)]
            gamma = self.gamma
            for nidxes in nstep_idxs:                   #for nn,nidxes for enumerate(nstep_idxs)
                data = self._storage[nidxes]
                _, _, r, nxtobs_t, done, _, _ = data
                reward += gamma*r                       #for less computation then np.power(self.gamma,nn+1)*r 
                gamma *= self.gamma
            obses_t.append(obs_t)
            actions.append(action)
            rewards.append(reward)
            nxtobses_t.append(nxtobs_t)
            dones.append(done)
        obses_t = [np.array(o) for o in list(zip(*obses_t))]
        actions = np.array(actions)
        rewards = np.array(rewards)
        nxtobses_t = [np.array(no) for no in list(zip(*nxtobses_t))]
        dones = np.array(dones)
        return (obses_t,
                actions,
                rewards,
                nxtobses_t,
                dones)

    def sample(self, batch_size: int):
        """
        Sample a batch of experiences.

        :param batch_size: (int) How many transitions to sample.
        :param env: (Optional[VecNormalize]) associated gym VecEnv
            to normalize the observations/rewards when sampling
        :return:
            - obs_batch: (np.ndarray) batch of observations
            - act_batch: (numpy float) batch of actions executed given obs_batch
            - rew_batch: (numpy float) rewards received as results of executing act_batch
            - next_obs_batch: (np.ndarray) next set of observations seen after executing act_batch
            - done_mask: (numpy bool) done_mask[i] = 1 if executing act_batch[i] resulted in the end of an episode
                and 0 otherwise.
        """
        idxes = [random.randint(0, len(self._storage) - 1) for _ in range(batch_size)]
        return self._encode_sample(idxes)
    
class PrioritizedEpisodicReplayBuffer(EpisodicReplayBuffer):
    def __init__(self, size, worker_size, n_step, gamma, alpha):
        """
        Create Prioritized Replay buffer.

        See Also ReplayBuffer.__init__

        :param size: (int) Max number of transitions to store in the buffer. When the buffer overflows the old memories
            are dropped.
        :param alpha: (float) how much prioritization is used (0 - no prioritization, 1 - full prioritization)
        """
        super(PrioritizedEpisodicReplayBuffer, self).__init__(size, worker_size, n_step, gamma)
        assert alpha >= 0
        self._alpha = alpha

        it_capacity = 1
        while it_capacity < size:
            it_capacity *= 2

        self._it_sum = SumSegmentTree(it_capacity)
        self._it_min = MinSegmentTree(it_capacity)
        self._max_priority = 1.0

    def add(self, obs_t, action, reward, nxtobs_t, done, worker, terminal):
        """
        add a new transition to the buffer

        :param obs_t: (Any) the last observation
        :param action: ([float]) the action
        :param reward: (float) the reward of the transition
        :param obs_tp1: (Any) the current observation
        :param done: (bool) is the episode done
        """
        idx = self._next_idx
        super().add(obs_t, action, reward, nxtobs_t, done, worker, terminal)
        self._it_sum[idx] = self._max_priority ** self._alpha
        self._it_min[idx] = self._max_priority ** self._alpha

    def _sample_proportional(self, batch_size):
        mass = []
        total = self._it_sum.sum(0, len(self._storage) - 1)
        # TODO(szymon): should we ensure no repeats?
        mass = np.random.random(size=batch_size) * total
        idx = np.array(self._it_sum.find_prefixsum_idx(mass))
        return idx

    def sample(self, batch_size: int, beta: float = 0):
        """
        Sample a batch of experiences.

        compared to ReplayBuffer.sample
        it also returns importance weights and idxes
        of sampled experiences.

        :param batch_size: (int) How many transitions to sample.
        :param beta: (float) To what degree to use importance weights (0 - no corrections, 1 - full correction)
        :param env: (Optional[VecNormalize]) associated gym VecEnv
            to normalize the observations/rewards when sampling
        :return:
            - obs_batch: (np.ndarray) batch of observations
            - act_batch: (numpy float) batch of actions executed given obs_batch
            - rew_batch: (numpy float) rewards received as results of executing act_batch
            - next_obs_batch: (np.ndarray) next set of observations seen after executing act_batch
            - done_mask: (numpy bool) done_mask[i] = 1 if executing act_batch[i] resulted in the end of an episode
                and 0 otherwise.
            - weights: (numpy float) Array of shape (batch_size,) and dtype np.float32 denoting importance weight of
                each sampled transition
            - idxes: (numpy int) Array of shape (batch_size,) and dtype np.int32 idexes in buffer of sampled experiences
        """
        assert beta > 0

        idxes = self._sample_proportional(batch_size)
        weights = []
        p_min = self._it_min.min() / self._it_sum.sum()
        max_weight = (p_min * len(self._storage)) ** (-beta)
        p_sample = self._it_sum[idxes] / self._it_sum.sum()
        weights = np.array((p_sample * len(self._storage)) ** (-beta) / max_weight)
        encoded_sample = self._encode_sample(idxes)
        return encoded_sample + (weights, idxes)

    def update_priorities(self, idxes, priorities):
        """
        Update priorities of sampled transitions.

        sets priority of transition at index idxes[i] in buffer
        to priorities[i].

        :param idxes: ([int]) List of idxes of sampled transitions
        :param priorities: ([float]) List of updated priorities corresponding to transitions at the sampled idxes
            denoted by variable `idxes`.
        """
        assert len(idxes) == len(priorities)
        assert np.min(priorities) > 0
        assert np.min(idxes) >= 0
        assert np.max(idxes) < len(self.storage)
        self._it_sum[idxes] = priorities ** self._alpha
        self._it_min[idxes] = priorities ** self._alpha

        self._max_priority = max(self._max_priority, np.max(priorities))*0.95