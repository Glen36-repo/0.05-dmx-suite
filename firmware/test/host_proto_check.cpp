// Host build of proto.h for tests/test_firmware_proto.py. Prints one "name hex" line per case.
// The Python test builds the same cases with dmx_suite.node.protocol and compares.
#include <stdio.h>

#include "../include/proto.h"

using namespace proto;

static void hex(const char* name, const uint8_t* d, size_t n) {
  printf("%s ", name);
  for (size_t i = 0; i < n; i++) printf("%02x", d[i]);
  printf("\n");
}

int main() {
  static uint8_t out[MAX_PAYLOAD + 6];
  static uint8_t buf[MAX_PAYLOAD];

  const char* check = "123456789";
  uint8_t c[2];
  put16(c, crc16((const uint8_t*)check, 9));
  hex("crc", c, 2);

  const char* key = "0.05-dev-key-change-me";
  uint8_t f[4];
  put32(f, fnv1a32((const uint8_t*)key, strlen(key)));
  hex("fnv", f, 4);

  uint8_t tok[4];
  put32(tok, 0x12345678);
  hex("ping", out, encode(out, MSG_PING, tok, 4));

  buf[0] = 0;
  for (int i = 0; i < 512; i++) buf[1 + i] = i & 0xFF;
  hex("frame", out, encode(out, MSG_DMX_FRAME, buf, 513));

  // heartbeat record
  Heartbeat hb = {};
  for (int i = 0; i < 6; i++) hb.mac[i] = 0xA0 + i;
  hb.node_type = DMX_RX;
  hb.fw[0] = 0; hb.fw[1] = 1; hb.fw[2] = 2;
  hb.uptime_s = 3600;
  hb.rssi = -67;
  hb.loss_pct = 3;
  hb.last_data_age_ms = 25;
  hb.universe = 0;
  memcpy(hb.name, "Left bars", 9);
  hex("heartbeat", out, encode(out, MSG_HEARTBEAT, (const uint8_t*)&hb, sizeof(hb)));

  Status st = {};
  st.uptime_ms = 123456; st.frames_rx = 4000; st.frame_rate_x10 = 400; st.crc_errors = 2;
  st.other_errors = 1; st.mode = LIVE; st.receivers_online = 3; st.flags = FLAG_DEV_KEY; st.channel = 6;
  hex("status", out, encode(out, MSG_STATUS, (const uint8_t*)&st, sizeof(st)));

  // v1.1: ACK with a request id, SET_CHANNEL with one, request_len
  uint8_t ack[3] = {MSG_ASSIGN, ACK_OK, 42};
  hex("ack_req", out, encode(out, MSG_ACK, ack, 3));
  uint8_t ch[2] = {11, 7};
  hex("set_channel", out, encode(out, MSG_SET_CHANNEL, ch, 2));
  bool has_req; uint8_t req;
  printf("request_len %d%d%d %d\n", request_len(23, 23, ch, has_req, req), request_len(24, 23, ch, has_req, req),
         request_len(25, 23, ch, has_req, req), (int)has_req);

  // fallback look: parse then render at several times
  uint16_t addrs[] = {1, 4, 100};
  size_t n = 0;
  put16(buf + n, 1500); n += 2;
  put16(buf + n, 6); n += 2;
  buf[n++] = 200;
  buf[n++] = 3;
  for (uint16_t a : addrs) { put16(buf + n, a); n += 2; }
  for (int i = 0; i < 512; i++) buf[n + i] = 0;
  buf[n + 9] = 255;  // ch 10 dimmer
  n += 512;
  Fallback fb;
  if (fb.parse(buf, n) != ACK_OK) { printf("fallback parse failed\n"); return 1; }
  printf("fallback_size %u\n", Fallback::size(buf, n));
  static uint8_t fbu[1 + MAX_PAYLOAD];
  fbu[0] = 2;
  memcpy(fbu + 1, buf, n);
  fbu[1 + n] = 9;  // request id
  static uint8_t big[MAX_PAYLOAD + 6];
  size_t bn = encode(big, MSG_SET_FALLBACK_U, fbu, 1 + n + 1);
  hex("set_fallback_u_head", big, 12);
  hex("set_fallback_u_tail", big + bn - 4, 4);
  uint8_t frame[512];
  const uint32_t times[] = {0, 999, 1000, 2500, 5999, 6000, 123457};
  for (uint32_t t : times) {
    render_fallback(fb, t, frame);
    char name[32];
    snprintf(name, sizeof(name), "fallback_%u", t);
    hex(name, frame, 12);
    char name2[32];
    snprintf(name2, sizeof(name2), "fallback_%u_hi", t);
    hex(name2, frame + 99, 3);
  }

  // parser: garbage, a corrupted frame, then two good frames
  Parser p;
  uint8_t stream[64];
  size_t sn = 0;
  stream[sn++] = 0x00; stream[sn++] = START; stream[sn++] = 0x99;  // junk incl. a false start
  size_t m = encode(stream + sn, MSG_PING, tok, 4);
  stream[sn + 5] ^= 0xFF;  // corrupt payload
  sn += m;
  sn += encode(stream + sn, MSG_PING, tok, 4);
  sn += encode(stream + sn, MSG_STATUS_REQ, nullptr, 0);
  int good = 0;
  for (size_t i = 0; i < sn; i++) {
    p.push(stream[i]);
    while (p.next()) good++;
  }
  printf("parser good=%d crc_errors=%u\n", good, p.crc_errors);
  return 0;
}
