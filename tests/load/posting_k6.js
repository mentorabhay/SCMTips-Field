import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 20 },
    { duration: '1m', target: 50 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const payload = JSON.stringify({
    delivery_no: '80000001',
    line_item_no: '000010',
    quantity: 1.0,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': `OBD:80000001:${__VU}:${__ITER}`,
    },
  };

  const res = http.post('http://localhost:8000/v1/warehouse/outbound/picks', payload, params);
  check(res, {
    'status is 200 or 201': (r) => r.status === 200 || r.status === 201,
  });
  sleep(0.1);
}
