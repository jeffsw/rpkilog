export class VrpEntry {
    constructor(asn, expires, maxLength, prefix, ta) {
        if (!(typeof(asn) === 'number' && Number.isInteger(asn) && asn >= 0 && asn < 4294967296)) {
            throw new TypeError('asn must be an integer between 0 and 4294967296');
        }
        this.asn = asn;

        if (typeof(expires) !== 'number' || expires < 1262322000 || expires > 4133912400) {
            throw new TypeError('expires must be a unix timestamp style number between 1262322000 and 4133912400');
        }
        this.expires = expires;
        this.expires_js = new Date(expires * 1000);
        this.expires_str = this.expires_js.toISOString().replace(/\.\d+/, '');

        if (!(typeof(maxLength === 'number' && Number.isInteger(maxLength)))) {
            throw new TypeError('maxLength must be an integer from 0-32 (for IPv4 prefixes) or 0-128 (IPv6)');
        }
        this.maxLength = maxLength

        if (prefix.match(/^([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})\/([0-9]{1,2})$/)) {
            this.family = 4
            if (!(this.maxLength >= 0 && this.maxLength <= 32)) {
                throw new TypeError('maxLength must be an integer from 0 to 32 for IPv4 prefixes');
            }
        } else if (prefix.match(/^([0-9A-Fa-f:]+:.+)\/(\d{1,3})$/)) {
            this.family = 6
            if (!(0 <= this.maxLength && this.maxLength <= 128)) {
                throw new TypeError('maxLength must be an integer from 0 to 128 for IPv6 prefixes');
            }
        } else {
            throw new TypeError(`prefix must be an IPv4 or IPv6 network prefix and length; you supplied: ${prefix}`);
        }
        this.prefix = prefix;

        if (typeof(ta) !== 'string') {
            throw new TypeError('ta must be a string like ARIN, RIPE, etc.');
        }
        this.ta = ta;
    }

    /**
     * Create a VrpEntry object given an argument object which may come from our HTTP API
     * @param {object} jo
     * @returns {VrpEntry}
     */
    static new_from_json_obj (jo) {
        let retval = new VrpEntry(
            jo.asn,
            jo.expires,
            jo.maxLength,
            jo.prefix,
            jo.ta
        );
        return retval
    }
}

export class VrpHistoryEntry {
    /**
     * A prefix may have many diff entries with various expiration times, TAs, max lengths, etc.
     * To retrieve some examples from the HTTP API, run `rpkilog-hapi --prefix 8.8.8.0/24 --paginate-size 2`
     */
    constructor(oldVrpEntry, newVrpEntry, observation_timestamp, verb, es_sort) {
        if (! oldVrpEntry instanceof VrpEntry) {
            throw new TypeError(`argument oldVrpEntry must be an instance of VrpEntry`);
        }
        if (! newVrpEntry instanceof VrpEntry) {
            throw new TypeError(`argument newVrpEntry must be an instance of VrpEntry`);
        }
        this.oldVrpEntry = oldVrpEntry;
        this.newVrpEntry = newVrpEntry;

        this.observation_timestamp = observation_timestamp;
        this.verb = verb;
        if (typeof(es_sort) !== 'undefined') {
            this.es_sort = es_sort
        }
    }

     /**
     * Returns a new VrpHistoryEntry when given a result entry from our HTTP API.
     * To retrieve some examples, run `rpkilog-hapi --prefix 8.8.8.0/24 --paginate-size 2`
     * @param {object} hapi_result_entry -- JSON object from the HTTP API
     * @return {VrpHistoryEntry}
     */
    static new_from_hapi_result_entry (hapi_result_entry) {
        let oldVrp = null;
        let newVrp = null;
        if (['UNCHANGED', 'REPLACE', 'DELETE'].includes(hapi_result_entry._source.verb)) {
            oldVrp = VrpEntry.new_from_json_obj(hapi_result_entry._source.old_roa);
        }
        if (['UNCHANGED', 'REPLACE', 'NEW'].includes(hapi_result_entry._source.verb)) {
            newVrp = VrpEntry.new_from_json_obj(hapi_result_entry._source.new_roa);
        }
        let retval = new VrpHistoryEntry(
            oldVrp,
            newVrp,
            hapi_result_entry._source.observation_timestamp,
            hapi_result_entry._source.verb,
            hapi_result_entry.sort
        );
        return retval
    }
}
