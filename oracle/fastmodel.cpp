// RIFT compiled fast models (C++17): the same cycle engine and network models as
// rift/model/{engine,networks,arbiters}.py, compiled for speed. Reads the
// compiled-workload text used by the RTL driver and writes the same summary (and
// optionally the same event schema). Cross-checked against the Python models by
// tests/test_fastmodel.py; neither implementation reads the other.
//
// usage: rift_fastmodel --family crossbar|shared_link|butterfly --num-in N --num-out M
//          [--fair 0|1] [--lock-in 0|1] [--bank-mod K] [--radix 2|4] [--links "g,s;g,s"]
//          [--resp-lat L] --batch LIST       (each line: workload summary events|-)

#include <chrono>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

struct Op { int master, index; uint32_t addr; bool after_response; int gap; };
struct Workload { std::string digest; int masters = 0; std::vector<std::vector<Op>> per; size_t total = 0; };

static bool parse(const std::string& path, int num_in, Workload& w) {
  std::ifstream in(path);
  std::string line;
  if (!std::getline(in, line) || line != "RIFT_COMPILED_WORKLOAD 1") return false;
  w.per.assign(num_in, {});
  while (std::getline(in, line)) {
    std::istringstream ss(line);
    std::string tag; ss >> tag;
    if (tag == "digest") ss >> w.digest;
    else if (tag == "masters") ss >> w.masters;
    else if (tag == "op") {
      Op o{}; std::string rel;
      ss >> o.master >> o.index >> o.addr >> rel >> o.gap;
      o.after_response = rel == "R";
      if (o.master < 0 || o.master >= num_in) return false;
      w.per[o.master].push_back(o); w.total++;
    } else if (tag == "end") return true;
  }
  return false;
}

static int clog2(int n) { int l = 0; while ((1 << l) < n) l++; return l; }

// ---- rr_arb_tree (pinned common_cells semantics) ---------------------------
struct RRArb {
  int n, levels; bool fair, lock_in, ext; int rr_q = 0; bool lock_q = false; uint32_t req_q = 0;
  RRArb(int n_, bool fair_, bool lock_, bool ext_) : n(n_), levels(clog2(n_)), fair(fair_), lock_in(lock_ && !ext_), ext(ext_) {}
  // returns winner (-1 none), sets req_d
  int select(uint32_t req, int prio, uint32_t& req_d) const {
    if (n == 1) { req_d = req; return (req & 1) ? 0 : -1; }
    req_d = (lock_in && lock_q) ? req_q : req;
    int p = ext ? prio : rr_q;
    if (!req_d) return -1;
    int width = 1 << (levels - 1);
    int nreq[64], nidx[64];
    int bit = p & 1;
    for (int l = 0; l < width; l++) {
      int i0 = 2 * l, i1 = 2 * l + 1;
      if (i0 < n - 1) { int r0 = (req_d >> i0) & 1, r1 = (req_d >> i1) & 1; nreq[l] = r0 | r1; nidx[l] = (!r0 || (r1 && bit)) ? 1 : 0; }
      else if (i0 == n - 1) { nreq[l] = (req_d >> i0) & 1; nidx[l] = 0; }
      else { nreq[l] = 0; nidx[l] = 0; }
    }
    int depth = 1;
    while (width > 1) {
      bit = (p >> depth) & 1;
      int nw = width >> 1;
      for (int l = 0; l < nw; l++) {
        int r0 = nreq[2 * l], r1 = nreq[2 * l + 1];
        bool sel = !r0 || (r1 && bit);
        int idx = sel ? ((1 << depth) | nidx[2 * l + 1]) : nidx[2 * l];
        nreq[l] = r0 | r1; nidx[l] = idx;
      }
      width = nw; depth++;
    }
    return nreq[0] ? nidx[0] : -1;
  }
  void update(uint32_t req_d, bool req_o, bool gnt_i) {
    if (ext || n == 1) return;
    if (req_o && gnt_i) {
      if (fair) {
        uint32_t upper = req_d & ~((rr_q + 1 >= 32) ? 0xFFFFFFFFu : ((1u << (rr_q + 1)) - 1));
        uint32_t pick = upper ? upper : (req_d & ((1u << (rr_q + 1)) - 1));
        rr_q = __builtin_ctz(pick);
      } else {
        rr_q = (rr_q == n - 1) ? 0 : rr_q + 1;
      }
    }
    if (lock_in) { lock_q = req_o && !gnt_i; req_q = req_d; }
  }
};

// ---- networks --------------------------------------------------------------
struct Net {
  virtual ~Net() {}
  // offers: word per master (-1 if not offering); returns acceptance mask
  virtual uint32_t cycle(const std::vector<int64_t>& offers) = 0;
};

struct Crossbar : Net {
  int ni, no, mod; std::vector<RRArb> arbs;
  Crossbar(int ni_, int no_, bool fair, bool lock, int mod_) : ni(ni_), no(no_), mod(mod_ ? mod_ : no_) {
    for (int b = 0; b < no; b++) arbs.emplace_back(ni, fair, lock, false);
  }
  uint32_t arbitrate(const std::vector<uint32_t>& reqs) {
    uint32_t granted = 0;
    for (int b = 0; b < no; b++) {
      RRArb& a = arbs[b];
      if (!reqs[b] && !(a.lock_in && a.lock_q)) { if (a.lock_in) { a.lock_q = false; a.req_q = 0; } continue; }
      uint32_t req_d; int w = a.select(reqs[b], 0, req_d);
      if (w >= 0) granted |= 1u << w;
      a.update(req_d, w >= 0, true);
    }
    return granted;
  }
  uint32_t cycle(const std::vector<int64_t>& offers) override {
    std::vector<uint32_t> reqs(no, 0);
    for (int m = 0; m < ni; m++) if (offers[m] >= 0) reqs[offers[m] % mod] |= 1u << m;
    return arbitrate(reqs);
  }
};

struct SharedLink : Crossbar {
  std::vector<std::pair<int, int>> links;
  std::vector<std::map<int64_t, RRArb>> larbs;
  SharedLink(int ni_, int no_, std::vector<std::pair<int, int>> l) : Crossbar(ni_, no_, true, false, 0), links(l), larbs(l.size()) {}
  uint32_t cycle(const std::vector<int64_t>& offers) override {
    std::vector<int64_t> surv = offers;
    struct Rec { RRArb* a; uint32_t req_d; int m; };
    std::vector<Rec> recs;
    for (size_t k = 0; k < links.size(); k++) {
      int g = links[k].first, s = links[k].second;
      std::map<int64_t, uint32_t> groups;
      for (int m = 0; m < ni; m++) if (surv[m] >= 0) groups[((int64_t)(m / g) << 32) | ((surv[m] % mod) >> s)] |= 1u << (m % g);
      std::vector<int64_t> nxt(ni, -1);
      for (auto& kv : groups) {
        auto it = larbs[k].find(kv.first);
        if (it == larbs[k].end()) it = larbs[k].emplace(kv.first, RRArb(g, true, false, false)).first;
        uint32_t req_d; int w = it->second.select(kv.second, 0, req_d);
        int m = (int)(kv.first >> 32) * g + w;
        nxt[m] = surv[m];
        recs.push_back({&it->second, req_d, m});
      }
      surv = nxt;
    }
    std::vector<uint32_t> reqs(no, 0);
    for (int m = 0; m < ni; m++) if (surv[m] >= 0) reqs[surv[m] % mod] |= 1u << m;
    uint32_t g = arbitrate(reqs);
    for (auto& r : recs) r.a->update(r.req_d, true, (g >> r.m) & 1);
    return g;
  }
};

struct Butterfly : Net {
  int ni, no, radix, addw, lr, levels, routers, bankfact, mod;
  std::vector<std::pair<int, int>> inmap;
  std::map<int64_t, std::pair<int, int>> wire;
  std::map<int64_t, RRArb> arbs;
  Butterfly(int ni_, int no_, int radix_, int mod_) : ni(ni_), no(no_), radix(radix_), mod(mod_ ? mod_ : no_) {
    addw = clog2(no); lr = clog2(radix); levels = (addw + lr - 1) / lr; routers = no / radix; bankfact = no / ni;
    inmap.assign(ni, {0, 0});
    for (int j = 0; j < radix * routers; j++) {
      if (bankfact < radix) { if (j % bankfact == 0) inmap[j / bankfact] = {j / radix, j % radix}; }
      else if (j % radix == 0 && j / radix < ni) inmap[j / radix] = {j / radix, 0};
    }
    for (int l = 0; l < levels - 1; l++) {
      int pw = 1; for (int t = 0; t < levels - l - 2; t++) pw *= radix;
      for (int r = 0; r < routers; r++) for (int s = 0; s < radix; s++) {
        int k = pw * s + (r % pw) + (r / pw / radix) * pw * radix;
        int j = (r / pw) % radix;
        wire[((int64_t)l << 40) | ((int64_t)r << 20) | s] = {k, j};
      }
    }
  }
  int port(int bank, int level) const { return (bank >> (addw - (level + 1) * lr)) & (radix - 1); }
  uint32_t cycle(const std::vector<int64_t>& offers) override {
    std::map<std::pair<int, int>, int> cur;
    std::vector<int> bank(ni, -1);
    for (int m = 0; m < ni; m++) if (offers[m] >= 0) { cur[inmap[m]] = m; bank[m] = offers[m] % mod; }
    struct Rec { RRArb* a; uint32_t req_d; int m; };
    std::vector<Rec> recs;
    for (int l = 0; l < levels; l++) {
      std::map<std::pair<int, int>, uint32_t> groups;
      for (auto& kv : cur) groups[{kv.first.first, port(bank[kv.second], l)}] |= 1u << kv.first.second;
      std::map<std::pair<int, int>, int> nxt;
      for (auto& g : groups) {
        int64_t key = ((int64_t)l << 40) | ((int64_t)g.first.first << 20) | g.first.second;
        auto it = arbs.find(key);
        if (it == arbs.end()) it = arbs.emplace(key, RRArb(radix, true, false, false)).first;
        uint32_t req_d; int w = it->second.select(g.second, 0, req_d);
        int m = cur[{g.first.first, w}];
        if (l < levels - 1) { auto kj = wire[key]; nxt[{kj.first, kj.second}] = m; }
        else nxt[g.first] = m;
        recs.push_back({&it->second, req_d, m});
      }
      cur = nxt;
    }
    uint32_t granted = 0;
    for (auto& kv : cur) granted |= 1u << kv.second;
    for (auto& r : recs) r.a->update(r.req_d, true, (granted >> r.m) & 1);
    return granted;
  }
};

// ---- engine ----------------------------------------------------------------
struct Result { std::string status; int64_t makespan = -1; uint64_t accepted = 0, completed = 0; int64_t last = -1; double secs = 0; };

static Result simulate(Net& net, const Workload& w, int ni, int no, int resp_lat, FILE* ev, const std::string& run_id) {
  auto t0 = std::chrono::steady_clock::now();
  Result r;
  const int first = 4;
  if (ev) for (int c = 0; c < first; c++)
    std::fprintf(ev, "{\"schema_version\":1,\"run_id\":\"%s\",\"cycle\":%d,\"sample_phase\":\"pre_rise\",\"event_kind\":\"reset\",\"master\":null,\"operation_index\":null,\"byte_address\":null}\n", run_id.c_str(), c);
  std::vector<size_t> nxt(ni, 0);
  std::vector<int> state(ni, 0); // 0 waiting 1 offering 2 done
  std::vector<int64_t> earliest(ni, first);
  std::vector<bool> known(ni, true);
  int done = 0;
  for (int m = 0; m < ni; m++) { if (w.per[m].empty()) { state[m] = 2; done++; } else earliest[m] = first + w.per[m][0].gap; }
  struct Pend { int64_t due; int m; int idx; };
  std::vector<Pend> pending;
  int64_t c = first;
  std::vector<int64_t> offers(ni, -1);
  auto emit = [&](const char* kind, int m, const Op& op, int64_t cyc, bool data) {
    uint32_t q = op.addr >> 2;
    std::fprintf(ev, "{\"schema_version\":1,\"run_id\":\"%s\",\"cycle\":%" PRId64 ",\"sample_phase\":\"pre_rise\",\"event_kind\":\"%s\",\"master\":%d,\"operation_index\":%d,\"byte_address\":%u,\"bank\":%u,\"row\":%u",
                 run_id.c_str(), cyc, kind, m, op.index, op.addr, q % no, q / no);
    if (data) std::fprintf(ev, ",\"read_data\":%u", (uint32_t)((q * 0x9E3779B1u) ^ 0xA5A55A5Au));
    std::fprintf(ev, "}\n");
  };
  while (true) {
    for (int m = 0; m < ni; m++) {
      offers[m] = -1;
      if (state[m] == 0 && known[m] && c >= earliest[m]) { state[m] = 1; if (ev) emit("offer", m, w.per[m][nxt[m]], c, false); }
      if (state[m] == 1) offers[m] = w.per[m][nxt[m]].addr >> 2;
    }
    std::vector<std::pair<int, int>> responded;
    for (size_t i = 0; i < pending.size();) {
      if (pending[i].due == c) {
        r.completed++; r.last = c; responded.push_back({pending[i].m, pending[i].idx});
        if (ev) emit("complete", pending[i].m, w.per[pending[i].m][pending[i].idx], c, true);
        pending[i] = pending.back(); pending.pop_back();
      } else i++;
    }
    uint32_t g = net.cycle(offers);
    for (int m = 0; m < ni; m++) if ((g >> m) & 1) {
      r.accepted++;
      if (ev) emit("accept", m, w.per[m][nxt[m]], c, false);
      pending.push_back({c + resp_lat, m, (int)nxt[m]});
    }
    for (auto& rp : responded) {
      int m = rp.first;
      if (state[m] == 0 && !known[m] && rp.second == (int)nxt[m] - 1) { known[m] = true; earliest[m] = c + 1 + w.per[m][nxt[m]].gap; }
    }
    for (int m = 0; m < ni; m++) if ((g >> m) & 1) {
      nxt[m]++;
      if (nxt[m] >= w.per[m].size()) { state[m] = 2; done++; }
      else {
        state[m] = 0;
        const Op& op = w.per[m][nxt[m]];
        if (!op.after_response) { known[m] = true; earliest[m] = c + 1 + op.gap; } else known[m] = false;
      }
    }
    int64_t active = c - first + 1;
    c++;
    if (done == ni && pending.empty()) { r.status = "COMPLETED"; break; }
    if (active >= 4096) { r.status = "TIMEOUT"; break; }
  }
  if (r.status == "COMPLETED" && r.last >= 0) r.makespan = r.last - first + 1;
  r.secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  return r;
}

int main(int argc, char** argv) {
  std::string family, batch, links_s;
  int ni = 8, no = 16, radix = 4, mod = 0, resp_lat = 1; bool fair = true, lock = true;
  for (int i = 1; i + 1 < argc; i += 2) {
    std::string a = argv[i], v = argv[i + 1];
    if (a == "--family") family = v; else if (a == "--num-in") ni = std::atoi(v.c_str()); else if (a == "--num-out") no = std::atoi(v.c_str());
    else if (a == "--fair") fair = v == "1"; else if (a == "--lock-in") lock = v == "1"; else if (a == "--bank-mod") mod = std::atoi(v.c_str());
    else if (a == "--radix") radix = std::atoi(v.c_str()); else if (a == "--links") links_s = v; else if (a == "--resp-lat") resp_lat = std::atoi(v.c_str());
    else if (a == "--batch") batch = v;
  }
  std::vector<std::pair<int, int>> links;
  { std::stringstream ss(links_s); std::string item; while (std::getline(ss, item, ';')) { int g, s; if (std::sscanf(item.c_str(), "%d,%d", &g, &s) == 2) links.push_back({g, s}); } }
  std::ifstream lst(batch);
  if (!lst) { std::fprintf(stderr, "usage: see header\n"); return 2; }
  std::string line; int n = 0;
  while (std::getline(lst, line)) {
    if (line.empty()) continue;
    std::istringstream ss(line);
    std::string wpath, spath, epath; ss >> wpath >> spath >> epath;
    Workload w;
    if (!parse(wpath, ni, w)) { std::fprintf(stderr, "INVALID_WORKLOAD %s\n", wpath.c_str()); return 3; }
    std::unique_ptr<Net> net;
    if (family == "crossbar") net.reset(new Crossbar(ni, no, fair, lock, mod));
    else if (family == "shared_link") net.reset(new SharedLink(ni, no, links));
    else if (family == "butterfly") net.reset(new Butterfly(ni, no, radix, mod));
    else { std::fprintf(stderr, "unknown family\n"); return 2; }
    FILE* ev = (epath.empty() || epath == "-") ? nullptr : std::fopen(epath.c_str(), "w");
    std::string rid = "fastmodel-" + std::to_string(n++);
    Result r = simulate(*net, w, ni, no, resp_lat, ev, rid);
    if (ev) std::fclose(ev);
    FILE* s = std::fopen(spath.c_str(), "w");
    std::fprintf(s, "{\"runner\":\"fast_model_compiled\",\"exit_status\":\"%s\",\"makespan\":%s,\"accepted\":%" PRIu64 ",\"completed\":%" PRIu64 ",\"elapsed_seconds\":%.9f}\n",
                 r.status.c_str(), r.makespan < 0 ? "null" : std::to_string(r.makespan).c_str(), r.accepted, r.completed, r.secs);
    std::fclose(s);
  }
  return 0;
}
