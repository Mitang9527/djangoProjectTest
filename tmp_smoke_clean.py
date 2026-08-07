import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djangoProjectTest.settings.dev')
django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS = ['*']

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from business.ai_studio.models import ApiChannel, UserChannelGrant, GenerationTask, UserQuota, QuotaTransaction

def jd(resp):
    b = resp.json()
    assert 'data' in b, (resp.status_code, str(b)[:200])
    return b['data']

U = get_user_model()
GenerationTask.objects.all().delete()
QuotaTransaction.objects.all().delete()
UserChannelGrant.objects.all().delete()
ApiChannel.objects.all().delete()
UserQuota.objects.all().delete()
U.objects.exclude(username='admin').delete()
print('PURGED residual test data', flush=True)

admin, _ = U.objects.get_or_create(username='admin')
admin.is_staff = True; admin.is_superuser = True; admin.save()

c = APIClient()
token = jd(c.post('/api/ai_studio/demo-login/', {'username': 'admin'}))['access']
c.credentials(HTTP_AUTHORIZATION='Bearer ' + token)
assert jd(c.get('/api/ai_studio/me/'))['is_staff'] is True

ch = jd(c.post('/api/ai_studio/channels/', {'name': '商品图 Agent', 'kind': 'AGENT', 'cost_per_call': 10, 'is_active': True}))
cid = ch['id']

u, _ = U.objects.get_or_create(username='alice')
cu = APIClient()
utoken = jd(cu.post('/api/ai_studio/demo-login/', {'username': 'alice'}))['access']
cu.credentials(HTTP_AUTHORIZATION='Bearer ' + utoken)

before = jd(cu.get('/api/ai_studio/my-channels/'))
assert before['count'] == 0, before
print('[OK] alice my-channels before grant = 0', flush=True)

g = jd(c.post('/api/ai_studio/grants/', {'username': 'alice', 'channel_id': cid, 'enabled': True}))
print('[OK] grant enabled =', g['enabled'], 'channel =', g['channel_name'], flush=True)

after = jd(cu.get('/api/ai_studio/my-channels/'))
assert after['count'] == 1, after
print('[OK] alice my-channels after grant = 1 ->', after['channels'][0]['name'], flush=True)

gen = jd(cu.post('/api/ai_studio/generate/', {'kind': 'image', 'count': 2, 'channel_id': cid}))
assert gen['cost'] == 20, gen
print('[OK] generate via channel cost =', gen['cost'], 'balance =', gen['quota']['balance'], flush=True)

adj = jd(c.post('/api/ai_studio/admin/grant/', {'username': 'alice', 'amount': 100, 'reason': 'test'}))
print('[OK] admin grant +100 -> balance', adj['balance'], flush=True)

c.delete(f'/api/ai_studio/grants/?username=alice&channel_id={cid}')
gen2 = cu.post('/api/ai_studio/generate/', {'kind': 'image', 'count': 1, 'channel_id': cid})
assert gen2.status_code == 403, gen2.status_code
print('[OK] after revoke generate status = 403', flush=True)

after2 = jd(cu.get('/api/ai_studio/my-channels/'))
assert after2['count'] == 0, after2
print('[OK] alice my-channels after revoke = 0', flush=True)

GenerationTask.objects.filter(user=u).delete()
QuotaTransaction.objects.all().delete()
UserChannelGrant.objects.all().delete()
ApiChannel.objects.all().delete()
UserQuota.objects.all().delete()
U.objects.exclude(username='admin').delete()
print('CLEANUP_DONE', flush=True)
