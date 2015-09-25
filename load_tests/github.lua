--------
-- START JSON Library Code
--------

-- Prosody IM
-- Copyright (C) 2008-2010 Matthew Wild
-- Copyright (C) 2008-2010 Waqas Hussain
--
-- This project is MIT/X11 licensed. Please see the
-- COPYING file in the source package for more information.
--

local type = type;
local t_insert, t_concat, t_remove, t_sort = table.insert, table.concat, table.remove, table.sort;
local s_char = string.char;
local tostring, tonumber = tostring, tonumber;
local pairs, ipairs = pairs, ipairs;
local next = next;
local error = error;
local newproxy, getmetatable, setmetatable = newproxy, getmetatable, setmetatable;
local print = print;

local has_array, array = pcall(require, "util.array");
local array_mt = has_array and getmetatable(array()) or {};

--module("json")
local json = {};

local null = newproxy and newproxy(true) or {};
if getmetatable and getmetatable(null) then
	getmetatable(null).__tostring = function() return "null"; end;
end
json.null = null;

local escapes = {
	["\""] = "\\\"", ["\\"] = "\\\\", ["\b"] = "\\b",
	["\f"] = "\\f", ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t"};
local unescapes = {
	["\""] = "\"", ["\\"] = "\\", ["/"] = "/",
	b = "\b", f = "\f", n = "\n", r = "\r", t = "\t"};
for i=0,31 do
	local ch = s_char(i);
	if not escapes[ch] then escapes[ch] = ("\\u%.4X"):format(i); end
end

local function codepoint_to_utf8(code)
	if code < 0x80 then return s_char(code); end
	local bits0_6 = code % 64;
	if code < 0x800 then
		local bits6_5 = (code - bits0_6) / 64;
		return s_char(0x80 + 0x40 + bits6_5, 0x80 + bits0_6);
	end
	local bits0_12 = code % 4096;
	local bits6_6 = (bits0_12 - bits0_6) / 64;
	local bits12_4 = (code - bits0_12) / 4096;
	return s_char(0x80 + 0x40 + 0x20 + bits12_4, 0x80 + bits6_6, 0x80 + bits0_6);
end

local valid_types = {
	number  = true,
	string  = true,
	table   = true,
	boolean = true
};
local special_keys = {
	__array = true;
	__hash  = true;
};

local simplesave, tablesave, arraysave, stringsave;

function stringsave(o, buffer)
	-- FIXME do proper utf-8 and binary data detection
	t_insert(buffer, "\""..(o:gsub(".", escapes)).."\"");
end

function arraysave(o, buffer)
	t_insert(buffer, "[");
	if next(o) then
		for i,v in ipairs(o) do
			simplesave(v, buffer);
			t_insert(buffer, ",");
		end
		t_remove(buffer);
	end
	t_insert(buffer, "]");
end

function tablesave(o, buffer)
	local __array = {};
	local __hash = {};
	local hash = {};
	for i,v in ipairs(o) do
		__array[i] = v;
	end
	for k,v in pairs(o) do
		local ktype, vtype = type(k), type(v);
		if valid_types[vtype] or v == null then
			if ktype == "string" and not special_keys[k] then
				hash[k] = v;
			elseif (valid_types[ktype] or k == null) and __array[k] == nil then
				__hash[k] = v;
			end
		end
	end
	if next(__hash) ~= nil or next(hash) ~= nil or next(__array) == nil then
		t_insert(buffer, "{");
		local mark = #buffer;
		if buffer.ordered then
			local keys = {};
			for k in pairs(hash) do
				t_insert(keys, k);
			end
			t_sort(keys);
			for _,k in ipairs(keys) do
				stringsave(k, buffer);
				t_insert(buffer, ":");
				simplesave(hash[k], buffer);
				t_insert(buffer, ",");
			end
		else
			for k,v in pairs(hash) do
				stringsave(k, buffer);
				t_insert(buffer, ":");
				simplesave(v, buffer);
				t_insert(buffer, ",");
			end
		end
		if next(__hash) ~= nil then
			t_insert(buffer, "\"__hash\":[");
			for k,v in pairs(__hash) do
				simplesave(k, buffer);
				t_insert(buffer, ",");
				simplesave(v, buffer);
				t_insert(buffer, ",");
			end
			t_remove(buffer);
			t_insert(buffer, "]");
			t_insert(buffer, ",");
		end
		if next(__array) then
			t_insert(buffer, "\"__array\":");
			arraysave(__array, buffer);
			t_insert(buffer, ",");
		end
		if mark ~= #buffer then t_remove(buffer); end
		t_insert(buffer, "}");
	else
		arraysave(__array, buffer);
	end
end

function simplesave(o, buffer)
	local t = type(o);
	if t == "number" then
		t_insert(buffer, tostring(o));
	elseif t == "string" then
		stringsave(o, buffer);
	elseif t == "table" then
		local mt = getmetatable(o);
		if mt == array_mt then
			arraysave(o, buffer);
		else
			tablesave(o, buffer);
		end
	elseif t == "boolean" then
		t_insert(buffer, (o and "true" or "false"));
	else
		t_insert(buffer, "null");
	end
end

function json.encode(obj)
	local t = {};
	simplesave(obj, t);
	return t_concat(t);
end
function json.encode_ordered(obj)
	local t = { ordered = true };
	simplesave(obj, t);
	return t_concat(t);
end
function json.encode_array(obj)
	local t = {};
	arraysave(obj, t);
	return t_concat(t);
end

-----------------------------------


local function _skip_whitespace(json, index)
	return json:find("[^ \t\r\n]", index) or index; -- no need to check \r\n, we converted those to \t
end
local function _fixobject(obj)
	local __array = obj.__array;
	if __array then
		obj.__array = nil;
		for i,v in ipairs(__array) do
			t_insert(obj, v);
		end
	end
	local __hash = obj.__hash;
	if __hash then
		obj.__hash = nil;
		local k;
		for i,v in ipairs(__hash) do
			if k ~= nil then
				obj[k] = v; k = nil;
			else
				k = v;
			end
		end
	end
	return obj;
end
local _readvalue, _readstring;
local function _readobject(json, index)
	local o = {};
	while true do
		local key, val;
		index = _skip_whitespace(json, index + 1);
		if json:byte(index) ~= 0x22 then -- "\""
			if json:byte(index) == 0x7d then return o, index + 1; end -- "}"
			return nil, "key expected";
		end
		key, index = _readstring(json, index);
		if key == nil then return nil, index; end
		index = _skip_whitespace(json, index);
		if json:byte(index) ~= 0x3a then return nil, "colon expected"; end -- ":"
		val, index = _readvalue(json, index + 1);
		if val == nil then return nil, index; end
		o[key] = val;
		index = _skip_whitespace(json, index);
		local b = json:byte(index);
		if b == 0x7d then return _fixobject(o), index + 1; end -- "}"
		if b ~= 0x2c then return nil, "object eof"; end -- ","
	end
end
local function _readarray(json, index)
	local a = {};
	local oindex = index;
	while true do
		local val;
		val, index = _readvalue(json, index + 1);
		if val == nil then
			if json:byte(oindex + 1) == 0x5d then return setmetatable(a, array_mt), oindex + 2; end -- "]"
			return val, index;
		end
		t_insert(a, val);
		index = _skip_whitespace(json, index);
		local b = json:byte(index);
		if b == 0x5d then return setmetatable(a, array_mt), index + 1; end -- "]"
		if b ~= 0x2c then return nil, "array eof"; end -- ","
	end
end
local _unescape_error;
local function _unescape_surrogate_func(x)
	local lead, trail = tonumber(x:sub(3, 6), 16), tonumber(x:sub(9, 12), 16);
	local codepoint = lead * 0x400 + trail - 0x35FDC00;
	local a = codepoint % 64;
	codepoint = (codepoint - a) / 64;
	local b = codepoint % 64;
	codepoint = (codepoint - b) / 64;
	local c = codepoint % 64;
	codepoint = (codepoint - c) / 64;
	return s_char(0xF0 + codepoint, 0x80 + c, 0x80 + b, 0x80 + a);
end
local function _unescape_func(x)
	x = x:match("%x%x%x%x", 3);
	if x then
		--if x >= 0xD800 and x <= 0xDFFF then _unescape_error = true; end -- bad surrogate pair
		return codepoint_to_utf8(tonumber(x, 16));
	end
	_unescape_error = true;
end
function _readstring(json, index)
	index = index + 1;
	local endindex = json:find("\"", index, true);
	if endindex then
		local s = json:sub(index, endindex - 1);
		--if s:find("[%z-\31]") then return nil, "control char in string"; end
		-- FIXME handle control characters
		_unescape_error = nil;
		--s = s:gsub("\\u[dD][89abAB]%x%x\\u[dD][cdefCDEF]%x%x", _unescape_surrogate_func);
		-- FIXME handle escapes beyond BMP
		s = s:gsub("\\u.?.?.?.?", _unescape_func);
		if _unescape_error then return nil, "invalid escape"; end
		return s, endindex + 1;
	end
	return nil, "string eof";
end
local function _readnumber(json, index)
	local m = json:match("[0-9%.%-eE%+]+", index); -- FIXME do strict checking
	return tonumber(m), index + #m;
end
local function _readnull(json, index)
	local a, b, c = json:byte(index + 1, index + 3);
	if a == 0x75 and b == 0x6c and c == 0x6c then
		return null, index + 4;
	end
	return nil, "null parse failed";
end
local function _readtrue(json, index)
	local a, b, c = json:byte(index + 1, index + 3);
	if a == 0x72 and b == 0x75 and c == 0x65 then
		return true, index + 4;
	end
	return nil, "true parse failed";
end
local function _readfalse(json, index)
	local a, b, c, d = json:byte(index + 1, index + 4);
	if a == 0x61 and b == 0x6c and c == 0x73 and d == 0x65 then
		return false, index + 5;
	end
	return nil, "false parse failed";
end
function _readvalue(json, index)
	index = _skip_whitespace(json, index);
	local b = json:byte(index);
	-- TODO try table lookup instead of if-else?
	if b == 0x7B then -- "{"
		return _readobject(json, index);
	elseif b == 0x5B then -- "["
		return _readarray(json, index);
	elseif b == 0x22 then -- "\""
		return _readstring(json, index);
	elseif b ~= nil and b >= 0x30 and b <= 0x39 or b == 0x2d then -- "0"-"9" or "-"
		return _readnumber(json, index);
	elseif b == 0x6e then -- "n"
		return _readnull(json, index);
	elseif b == 0x74 then -- "t"
		return _readtrue(json, index);
	elseif b == 0x66 then -- "f"
		return _readfalse(json, index);
	else
		return nil, "value expected";
	end
end
local first_escape = {
	["\\\""] = "\\u0022";
	["\\\\"] = "\\u005c";
	["\\/" ] = "\\u002f";
	["\\b" ] = "\\u0008";
	["\\f" ] = "\\u000C";
	["\\n" ] = "\\u000A";
	["\\r" ] = "\\u000D";
	["\\t" ] = "\\u0009";
	["\\u" ] = "\\u";
};

function json.decode(json)
	json = json:gsub("\\.", first_escape) -- get rid of all escapes except \uXXXX, making string parsing much simpler
		--:gsub("[\r\n]", "\t"); -- \r\n\t are equivalent, we care about none of them, and none of them can be in strings

	-- TODO do encoding verification

	local val, index = _readvalue(json, 1);
	if val == nil then return val, index; end
	if json:find("[^ \t\r\n]", index) then return nil, "garbage at eof"; end

	return val;
end

function json.test(object)
	local encoded = json.encode(object);
	local decoded = json.decode(encoded);
	local recoded = json.encode(decoded);
	if encoded ~= recoded then
		print("FAILED");
		print("encoded:", encoded);
		print("recoded:", recoded);
	else
		print(encoded);
	end
	return encoded == recoded;
end

--------
-- END JSON Library Code
--------

mode = "local"

if mode == "loadimpact" then
   base_url = "http://lightning.example.com"
   max_response_size = 32768
else
   http = require "socket.http"
   ltn12 = require "ltn12"
   inspect = require "inspect"
   base_url = "http://localhost:5001"
end


AllChars = ''
for Loop=0,255 do
	AllChars=AllChars..string.char(Loop)
end

function random_string(Length,Pattern)

   -- Length (number)
   -- Pattern (string, optional); e.g. %l%d for lower case letters and digits

   local Pattern,Random = Pattern or '.',''

   local String=string.gsub(AllChars,'[^'..Pattern..']','')

   for Loop=1,Length do
      Random=Random..
         string.char(string.byte(String,math.random(1,string.len(String))))
   end

   return Random
end

function make_request(method, path, data)
   url = base_url .. path;
   if mode == "loadimpact" then
      resp = http.request{method, url, data=data, response_body_bytes=max_response_size}
      body = resp.body
      status_code = resp.status_code
   else
      local sink_t = {}
      if method == "POST" then
         req_headers = {
            ["Content-Type"] = "application/x-www-form-urlencoded",
            ["content-length"] = string.len(data)
         }

         has_body, status_code, headers, status_msg = http.request{method = method, url = url,
                 headers = req_headers, source = ltn12.source.string(data), sink = ltn12.sink.table(sink_t)}
      else
         has_body, status_code, headers, status_msg = http.request{method = method, url = url,
                 sink = ltn12.sink.table(sink_t)}
      end

      body = table.concat(sink_t)
   end

   if not string.find(status_code, "^2") then
      print("Unexpected status code: " .. status_code .. " while fetching: " .. url)
   end
   return json.decode(body)
end

function assert_true(exp, msg)
   if not exp then
      out = "Assertion failed!: " .. msg
      print(out)
   end
   return exp
end

function assert_hash_contains(hash, key, msg)
   if assert_true(hash, msg) then
      return assert_true(hash[key], msg)
   else
      return false
   end
end

function sleep()
   if mode == "loadimpact" then
      client.sleep(math.random(10000, 20000), 1000)
   end
end

now = os.time()
math.randomseed(now)
month_ago = now - (30 * 24 * 60 * 60)

-- Authorize a new user

resp = make_request("GET", "/auth?redirect_uri=https%3A%2F%2Fintranet.example.com%2Fid%2Fauth%2Fcallback%2Fgithub&service=github")
assert_hash_contains(resp, 'redirect', "auth response must have redirect")

sleep()
code = random_string(10, '%l%d')
state = random_string(10, '%l%d')

resp = make_request("POST", "/auth", "redirect_uri=https%3A%2F%2Fintranet.example.com%2Fid%2Fauth%2Fcallback%2Fgithub&service=github&code=" .. code .. "&state=" .. state)
if assert_hash_contains(resp, 'guid', "finish auth must give us a guid") then
   guid = resp['guid']

   -- Get their profile
   sleep()
   resp = make_request("GET", "/api/github/profile?guid=" .. guid)
   assert_hash_contains(resp, 'name', "profile response must have name")

   -- Get each view

   sleep()
   views = {"GitHub", "GitHub_stats", "GitHub_details"}
   for i, view in pairs(views) do
      resp = make_request("GET", "/view/" .. view .. "/invoke?guid=" .. guid .. "&start=" .. month_ago .. "&end=" .. now)
      entry = resp["result"][1]
      assert_hash_contains(entry, 'method', "view entries must have methods")
   end

   -- Get the tip of the stream to simulate most_recent_activity.  Since the filtered responses have random user_ids
   -- all of the stream shows up as echo data.  most_recent_activity filters out echo data, so when we fetch the view
   -- above, we don't get anything for most_recent_activity and don't really do any significant processing,  Thus,
   -- get the tip of the stream to simulate doing what we *would* be doing if we got most_recent_activity

   resp = make_request("GET", "/stream?num=1&guid=" .. guid)
   assert_hash_contains(resp, 'data', "stream response must have data")

   -- Get the full stream

   sleep()
   resp = make_request("GET", "/stream?guid=" .. guid)
   assert_hash_contains(resp, 'data', "stream response must have data")
end
