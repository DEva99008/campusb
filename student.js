'use strict';

const DATA_KEY = 'campusbite_simple_v1';
const SESSION_KEY = 'campusbite_student_session';
const $ = id => document.getElementById(id);
const money = amount => '₹' + Number(amount || 0).toLocaleString('en-IN');
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

function readJSON(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch (error) {
    console.error(`Could not read ${key}:`, error);
    $('studentPortalError').textContent = 'Your saved CampusBite data could not be read. Check browser storage settings.';
    $('studentPortalError').classList.remove('hidden');
    return fallback;
  }
}

async function startPortal() {
  const session = readJSON(SESSION_KEY, null);
  if (!session?.id) {
    window.location.replace('student-login.html');
    return;
  }
  if (window.CampusBiteBackend && session.accessToken) {
    try {
      if (!await window.CampusBiteBackend.check()) {
        throw new Error('The CampusBite local database server is not running. Start it and refresh this page.');
      }
      const remote = await window.CampusBiteBackend.state();
      if (remote.role !== 'Student' || remote.loginId?.toLowerCase() !== session.id.toLowerCase()) {
        throw new Error('This session is not an active student account. Sign in again.');
      }
      localStorage.setItem(DATA_KEY, JSON.stringify(remote.state));
    } catch (error) {
      console.error('Could not load the student data from SQLite:', error);
      $('studentPortalError').textContent = error.message || 'Could not load the local database.';
      $('studentPortalError').classList.remove('hidden');
      return;
    }
  }
  const database = readJSON(DATA_KEY, {});
  const account = (Array.isArray(database.students) ? database.students : []).find(student =>
    String(student.id).toLowerCase() === String(session.id).toLowerCase() && student.role === 'Student'
  );
  if (!account || account.status !== 'Active') {
    localStorage.removeItem(SESSION_KEY);
    window.location.replace('student-login.html');
    return;
  }

  $('studentDisplayName').textContent = account.name;
  $('studentPoints').textContent = Number(database.points?.[account.id.toLowerCase()] || 0);
  const orders = (Array.isArray(database.orders) ? database.orders : [])
    .filter(order => String(order.studentId).toLowerCase() === account.id.toLowerCase())
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
  $('studentOrderCount').textContent = orders.length;
  const openCanteens = (Array.isArray(database.stalls) ? database.stalls : []).filter(stall =>
    stall.status === 'Open'
  ).length;
  $('openCanteenCount').textContent = openCanteens;
  const shops = (Array.isArray(database.stalls) ? database.stalls : []).filter(stall => stall.status === 'Open');
  $('studentShops').innerHTML = shops.length
    ? shops.map(stall => `<a class="campus-place" href="shop.html?shop=${encodeURIComponent(stall.id)}"><span class="place-marker food-marker">⌂</span><span><b>${esc(stall.name)}</b><small>${esc(stall.location || stall.shopGroup || 'KPRCAS campus')} · ${esc(stall.hours || 'Open')}</small></span><span class="place-arrow">→</span></a>`).join('')
    : '<p class="empty-state">No campus shops are open right now.</p>';

  const announcement = (Array.isArray(database.announcements) ? database.announcements : []).find(item => item.active);
  $('studentAnnouncement').innerHTML = announcement
    ? `<article class="student-notice"><span>✦</span><div><b>${esc(announcement.title)}</b><p>${esc(announcement.message)}</p></div></article>`
    : '<p class="muted-copy">No new campus updates right now. Check back before your next break.</p>';

  $('studentOrders').innerHTML = orders.length
    ? orders.slice(0, 6).map(order => {
      const stall = (database.stalls || []).find(item => item.id === order.stallId);
      return `<article class="student-order-row"><div class="student-order-id"><b>${esc(order.id)}</b><small>${new Date(order.createdAt).toLocaleString()}</small></div><div class="student-order-details"><span>${order.items.map(item => `${esc(item.name)} × ${item.qty}`).join(', ')}</span><small>${esc(stall?.name || 'KPRCAS canteen')} · ${esc(order.paymentStatus)}</small></div><span class="badge">${esc(order.status)}</span><strong>${money(order.total)}</strong></article>`;
    }).join('')
    : '<div class="empty-state">No orders yet. Browse the menu and order from the New Canteen or Old Canteen.</div>';
}

$('studentSignOut').addEventListener('click', () => {
  if (window.CampusBiteBackend) {
    window.CampusBiteBackend.logout().catch(error => console.error('Could not close the student database session:', error));
  }
  localStorage.removeItem(SESSION_KEY);
  window.location.replace('index.html');
});
window.addEventListener('storage', event => {
  if (event.key === DATA_KEY || event.key === SESSION_KEY) startPortal();
});
startPortal();
