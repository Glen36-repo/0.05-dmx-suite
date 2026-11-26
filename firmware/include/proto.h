// 0.05 node link protocol v1.1. Spec: docs/PROTOCOL.md. Must match dmx_suite/node/protocol.py.
// v1.1 (firmware 0.2) only adds to v1: new messages, an optional request id at the end of
// requests that get an ACK, and two bytes at the end of STATUS. A v1 laptop still works.
// Plain C++ (no Arduino headers) so tests can compile it on the host.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace proto {

constexpr uint8_t START = 0xA5;
constexpr uint16_t MAX_PAYLOAD = 1100;
constexpr uint16_t DMX_CHANNELS = 512;
constexpr uint8_t NAME_LEN = 16;
constexpr uint8_t MAX_FALLBACK_RGB = 32;
constexpr int8_t RSSI_NA = 127;
constexpr uint8_t LOSS_NA = 255;
constexpr uint32_t AGE_NEVER = 0xFFFFFFFFu;
constexpr uint8_t UNIVERSE_NONE = 0xFF;
constexpr uint8_t UNIVERSE_ALL = 0xFF;
constexpr uint16_t HUE_STEPS = 1536;
constexpr uint8_t MAX_UNIVERSES = 16;  // universes the node keeps frames, sequence numbers and keep-alives for
constexpr uint8_t MAX_FALLBACKS = 4;   // universes that can have their own stored fallback look
constexpr uint8_t MIN_CHANNEL = 1, MAX_CHANNEL = 13;
constexpr uint8_t FLAG_DEV_KEY = 0x01;   // STATUS flags: built with the development pairing key
constexpr uint8_t FLAG_DMX_FAIL = 0x02;  // the wired DMX driver didn't start

enum MsgType : uint8_t {
  MSG_DMX_FRAME = 0x01,
  MSG_BLACKOUT = 0x02,
  MSG_PING = 0x03,
  MSG_SET_FALLBACK = 0x04,
  MSG_ASSIGN = 0x05,
  MSG_IDENTIFY = 0x06,
  MSG_STATUS_REQ = 0x07,
  MSG_SET_FALLBACK_U = 0x08,  // v1.1: fallback look for one universe
  MSG_SET_CHANNEL = 0x09,     // v1.1: move the node and its receivers to another radio channel
  MSG_STATUS = 0x81,
  MSG_HEARTBEAT = 0x82,
  MSG_ANNOUNCE = 0x83,
  MSG_PONG = 0x84,
  MSG_ACK = 0x85,
  MSG_LOG = 0x86,
};

enum AckCode : uint8_t { ACK_OK = 0, ACK_BAD_LENGTH = 1, ACK_BAD_VALUE = 2, ACK_UNKNOWN_TARGET = 3, ACK_STORAGE_ERROR = 4, ACK_UNKNOWN_TYPE = 5 };
enum NodeType : uint8_t { DMX_TX = 1, DMX_RX = 2, MIDI = 3 };
enum Mode : uint8_t { LIVE = 0, FALLBACK = 1, BLACKOUT_MODE = 2 };

// Parsers reject unknown types at the header so a stray 0xA5 can't stall them waiting for a bogus length.
inline bool known_type(uint8_t t) { return (t >= 0x01 && t <= 0x09) || (t >= 0x81 && t <= 0x86); }

// v1.1 request ids: a request that gets an ACK may carry one extra byte, echoed in the ACK, so the
// laptop can tell which of several requests an ACK answers. Returns false if the length is wrong.
inline bool request_len(uint16_t len, uint16_t want, const uint8_t* p, bool& has_req, uint8_t& req) {
  if (len == want) { has_req = false; req = 0; return true; }
  if (len == want + 1) { has_req = true; req = p[want]; return true; }
  return false;
}

// ------------------------------------------------------------------ little-endian helpers

inline void put16(uint8_t* p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
inline void put32(uint8_t* p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
inline uint16_t get16(const uint8_t* p) { return p[0] | (p[1] << 8); }
inline uint32_t get32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }

// CRC-16/CCITT-FALSE
inline uint16_t crc16(const uint8_t* d, size_t n, uint16_t crc = 0xFFFF) {
  while (n--) {
    crc ^= (uint16_t)(*d++) << 8;
    for (int i = 0; i < 8; i++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
  }
  return crc;
}

inline uint32_t fnv1a32(const uint8_t* d, size_t n) {
  uint32_t h = 0x811C9DC5u;
  while (n--) h = (h ^ *d++) * 0x01000193u;
  return h;
}

// Encode a USB message into out (needs len + 6 bytes). Returns bytes written.
inline size_t encode(uint8_t* out, uint8_t type, const uint8_t* payload, uint16_t len) {
  out[0] = START;
  out[1] = type;
  put16(out + 2, len);
  if (len) memcpy(out + 4, payload, len);
  put16(out + 4 + len, crc16(out + 1, 3 + len));
  return 6 + len;
}

// ------------------------------------------------------------------ USB stream parser (resyncs on error)
// Usage: parser.push(byte); while (parser.next()) handle(parser.type, parser.payload, parser.len);

class Parser {
 public:
  uint32_t crc_errors = 0;
  uint8_t type = 0;
  uint16_t len = 0;
  uint8_t payload[MAX_PAYLOAD];

  void push(uint8_t b) {
    if (n_ == sizeof(buf_)) drop(1);  // cannot happen with valid lengths; keeps us safe
    buf_[n_++] = b;
  }

  // Extract the next complete, valid message. Returns false when more bytes are needed.
  bool next() {
    for (;;) {
      size_t i = 0;
      while (i < n_ && buf_[i] != START) i++;
      if (i) drop(i);
      if (n_ >= 2 && !known_type(buf_[1])) { crc_errors++; drop(1); continue; }
      if (n_ < 4) return false;
      uint16_t l = get16(buf_ + 2);
      if (l > MAX_PAYLOAD) { crc_errors++; drop(1); continue; }
      if (n_ < (size_t)l + 6) return false;
      if (get16(buf_ + 4 + l) != crc16(buf_ + 1, 3 + l)) { crc_errors++; drop(1); continue; }
      type = buf_[1];
      len = l;
      memcpy(payload, buf_ + 4, l);
      drop(l + 6);
      return true;
    }
  }

 private:
  uint8_t buf_[MAX_PAYLOAD + 6];
  size_t n_ = 0;
  void drop(size_t k) {
    memmove(buf_, buf_ + k, n_ - k);
    n_ -= k;
  }
};

// ------------------------------------------------------------------ records

#pragma pack(push, 1)
struct Heartbeat {  // 37 bytes
  uint8_t mac[6];
  uint8_t node_type;
  uint8_t fw[3];
  uint32_t uptime_s;
  int8_t rssi;
  uint8_t loss_pct;
  uint32_t last_data_age_ms;
  uint8_t universe;
  char name[NAME_LEN];
};
struct Status {  // 20 bytes (v1: the first 18)
  uint32_t uptime_ms;
  uint32_t frames_rx;
  uint16_t frame_rate_x10;
  uint32_t crc_errors;
  uint16_t other_errors;
  uint8_t mode;
  uint8_t receivers_online;
  uint8_t flags;    // FLAG_*
  uint8_t channel;  // radio channel in use
};
#pragma pack(pop)
static_assert(sizeof(Heartbeat) == 37, "heartbeat size");
static_assert(sizeof(Status) == 20, "status size");
// ESP32 and x86 are both little-endian, so packed structs are the wire format.

// ------------------------------------------------------------------ fallback look

struct Fallback {
  uint16_t hold_ms = 2000;
  uint16_t period_s = 0;
  uint8_t level = 0;
  uint8_t n_rgb = 0;
  uint16_t rgb_addr[MAX_FALLBACK_RGB] = {};
  uint8_t base[DMX_CHANNELS] = {};
  bool valid = false;  // false = fallback is full black

  // Length of a fallback payload starting at p (0 if too short to tell).
  static uint16_t size(const uint8_t* p, uint16_t len) {
    return len < 6 ? 0 : 6 + 2 * p[5] + DMX_CHANNELS;
  }

  // Returns AckCode.
  uint8_t parse(const uint8_t* p, uint16_t len) {
    if (len < 6) return ACK_BAD_LENGTH;
    uint8_t n = p[5];
    if (n > MAX_FALLBACK_RGB) return ACK_BAD_VALUE;
    if (len != 6 + 2 * n + DMX_CHANNELS) return ACK_BAD_LENGTH;
    for (uint8_t i = 0; i < n; i++) {
      uint16_t a = get16(p + 6 + 2 * i);
      if (a < 1 || a > DMX_CHANNELS - 2) return ACK_BAD_VALUE;
    }
    hold_ms = get16(p);
    period_s = get16(p + 2);
    level = p[4];
    n_rgb = n;
    for (uint8_t i = 0; i < n; i++) rgb_addr[i] = get16(p + 6 + 2 * i);
    memcpy(base, p + 6 + 2 * n, DMX_CHANNELS);
    valid = true;
    return ACK_OK;
  }
};

inline void hue_rgb(uint32_t h, uint8_t& r, uint8_t& g, uint8_t& b) {
  h %= HUE_STEPS;
  uint8_t f = h & 0xFF, up = f, down = 255 - f;
  switch (h >> 8) {
    case 0: r = 255; g = up; b = 0; break;
    case 1: r = down; g = 255; b = 0; break;
    case 2: r = 0; g = 255; b = up; break;
    case 3: r = 0; g = down; b = 255; break;
    case 4: r = up; g = 0; b = 255; break;
    default: r = 255; g = 0; b = down; break;
  }
}

inline void render_fallback(const Fallback& fb, uint32_t elapsed_ms, uint8_t* out /*512*/) {
  if (!fb.valid) { memset(out, 0, DMX_CHANNELS); return; }
  memcpy(out, fb.base, DMX_CHANNELS);
  uint32_t h = 0;
  if (fb.period_s) {
    uint32_t period_ms = (uint32_t)fb.period_s * 1000;
    h = (uint32_t)((uint64_t)(elapsed_ms % period_ms) * HUE_STEPS / period_ms);
  }
  uint8_t r, g, b;
  hue_rgb(h, r, g, b);
  r = r * fb.level / 255; g = g * fb.level / 255; b = b * fb.level / 255;
  for (uint8_t i = 0; i < fb.n_rgb; i++) {
    uint8_t* c = out + fb.rgb_addr[i] - 1;
    c[0] = r; c[1] = g; c[2] = b;
  }
}

// ------------------------------------------------------------------ ESP-NOW packets

namespace radio {
constexpr uint8_t MAGIC0 = 'O', MAGIC1 = '5', VERSION = 1;
constexpr uint8_t DMX_CHUNK = 0x01, ASSIGN = 0x02, IDENTIFY = 0x03, SET_CHANNEL = 0x04, HEARTBEAT = 0x10;
constexpr uint8_t CHUNK_MAX = 200;
constexpr uint16_t CHUNK_SIZE = 171;  // 512 = 171 + 171 + 170

#pragma pack(push, 1)
struct Header {
  uint8_t magic[2];
  uint8_t version;
  uint8_t kind;
  uint32_t net_id;
};
struct DmxChunk {
  Header h;
  uint8_t universe;
  uint8_t seq;
  uint16_t offset;
  uint8_t len;
  uint8_t data[CHUNK_MAX];
};
struct Assign {
  Header h;
  uint8_t mac[6];
  uint8_t universe;
  char name[NAME_LEN];
};
struct Identify {
  Header h;
  uint8_t mac[6];
  uint8_t seconds;
};
struct Beat {
  Header h;
  proto::Heartbeat hb;
};
struct SetChannel {
  Header h;
  uint8_t channel;
};
#pragma pack(pop)
static_assert(sizeof(DmxChunk) <= 250, "ESP-NOW v1 max payload");

inline void header(Header& h, uint8_t kind, uint32_t net_id) {
  h.magic[0] = MAGIC0; h.magic[1] = MAGIC1; h.version = VERSION; h.kind = kind; h.net_id = net_id;
}
inline bool valid(const uint8_t* d, int len, uint32_t net_id) {
  if (len < (int)sizeof(Header)) return false;
  const Header* h = (const Header*)d;
  return h->magic[0] == MAGIC0 && h->magic[1] == MAGIC1 && h->version == VERSION && h->net_id == net_id;
}
}  // namespace radio

}  // namespace proto
