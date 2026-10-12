'use strict';

(() => {
  const TOKEN_KEY = 'campusbite_local_access_token';
  let statusPromise;
  let available = false;
  let saveQueue = Promise.resolve();

  async function check() {
    if (!statusPromise) {
      statusPromise = fetch('/api/health', { cache: 'no-store' })
        .then(response => {
          available = response.ok;
          return available;
        })
        .catch(() => false);
    }
    return statusPromise;
  }

  function token() {
    return localStorage.getItem(TOKEN_KEY) || '';
  }

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (token()) headers.set('Authorization', `Bearer ${token()}`);
    if (options.body) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, { ...options, headers, cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Local database request failed (${response.status}).`);
    return payload;
  }

  window.CampusBiteBackend = {
    check,
    isAvailable() {
      return available;
    },
    async login(loginId, password) {
      const result = await request('/api/login', {
        method: 'POST',
        body: JSON.stringify({ loginId, password })
      });
      localStorage.setItem(TOKEN_KEY, result.access_token);
      return result;
    },
    async logout() {
      try {
        await saveQueue;
        if (token()) await request('/api/logout', { method: 'POST', body: '{}' });
      } finally {
        localStorage.removeItem(TOKEN_KEY);
      }
    },
    async state() {
      return request('/api/state');
    },
    async saveAdminState(state) {
      const write = saveQueue.then(() => request('/api/state', {
        method: 'PUT',
        body: JSON.stringify({ state })
      }));
      saveQueue = write.catch(error => {
        console.error('CampusBite SQLite save failed:', error);
      });
      return write;
    },
    async placeOrder(order) {
      return request('/api/orders', {
        method: 'POST',
        body: JSON.stringify(order)
      });
    },
    async updateOrderStatus(orderId, status) {
      return request('/api/orders/status', {
        method: 'POST',
        body: JSON.stringify({ orderId, status })
      });
    },
    async createUser(user) {
      return request('/api/users', {
        method: 'POST',
        body: JSON.stringify(user)
      });
    },
    async setShopPassword(loginId, password) {
      return request('/api/users/password', {
        method: 'POST',
        body: JSON.stringify({ loginId, password })
      });
    },
    clearToken() {
      localStorage.removeItem(TOKEN_KEY);
    }
  };
})();
