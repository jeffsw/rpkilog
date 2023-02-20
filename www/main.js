import { VrpEntry, VrpHistoryEntry } from './rpkilog.js';

var RPKI_HAPI_RESULT = {};
var RPKI_HISTORY_ENTRIES = [];

function check_for_deeplink_in_url (event) {
    // Invoked at DOMContentLoaded.  Check the document URL and if it has get params, populate the
    // search form and invoke a query.  This allows sharing links right to a set of search results.

    let url = new URL(document.URL);
    if (url.search.length == 0) {
        return;
    }
    let params = new URLSearchParams(url.search);
    let field_list = [
        'asn',
        'observation_timestamp_start',
        'observation_timestamp_end',
        'prefix',
    ];
    for (let field of field_list) {
        if (params.has(field)) {
            document.querySelector('#' + field).value = params.get(field);
        }
    }
    document.querySelector('#rpki_history_search_button').click();
}

function create_clickable_pagination_span (page_number, entries_per_page) {
    let retspan = document.createElement('SPAN');
    retspan.classList.add('paginate_clickable');
    retspan.innerText = page_number;
    retspan.dataset.page_number = page_number;
    retspan.addEventListener('click', display_history_page_onclick_handler);
    return retspan
}

function create_table_row_from_history_entry (entry) {
    let row = document.querySelector("#vrp_history_row").content.querySelector("tr").cloneNode(true);
    row.id = null;

    const vrp_prop_to_html_field = {
        'asn': 'asn',
        'expires_str': 'expires',
        'maxLength': 'maxLength',
        'prefix': 'prefix',
        'ta': 'ta',
    };
    for (const [prop, html_field] of Object.entries(vrp_prop_to_html_field)) {
        let cell = row.querySelector(`[data-field-name='${html_field}']`);
        let deleted, inserted;
        switch (entry.verb) {
            case 'UNCHANGED':
                cell.innerText = entry.newVrpEntry[prop];
                break;
            case 'NEW':
                inserted = document.createElement('INS');
                inserted.innerText = entry.newVrpEntry[prop];
                cell.appendChild(inserted);
                break;
            case 'DELETE':
                deleted = document.createElement('DEL');
                deleted.innerText = entry.oldVrpEntry[prop];
                cell.appendChild(deleted);
                break;
            case 'REPLACE':
                if (entry.oldVrpEntry[prop] === entry.newVrpEntry[prop]) {
                    // Identical values, so the output needs to make that clear
                    cell.innerText = entry.newVrpEntry[prop];
                } else {
                    // Changed values will get a strikethrough effect so it's obvious what is different
                    deleted = document.createElement('DEL');
                    deleted.innerText = entry.oldVrpEntry[prop];
                    cell.appendChild(deleted);
                    cell.appendChild(document.createElement('BR'))
                    inserted = document.createElement('INS');
                    inserted.innerText = entry.newVrpEntry[prop];
                    cell.appendChild(inserted);    
                }
                break;
            default:
                console.error(`Unrecognized vrp_diff verb ${entry.verb}`, entry);
        }
    }
    let verb_cell = row.querySelector("[data-field-name='verb']");
    verb_cell.innerText = entry.verb;
    let obstime_cell = row.querySelector("[data-field-name='observation_timestamp']");
    obstime_cell.innerText = entry.observation_timestamp;

    return row;
};

function display_history_entries (offset) {
    /**
     * Display history entries by populating the #vrp_history_table.
     * Entries before offset will not be displayed.
     * A maximum of size entries will be displayed.
     */

    const numEntries = get_paginate_num_entries_per_page();

    let table_rows = new Array();
    for (let i = offset; i < RPKI_HISTORY_ENTRIES.length && i < offset + numEntries; i++) {
        let entry = RPKI_HISTORY_ENTRIES[i];
        table_rows.push(create_table_row_from_history_entry(entry));
    }
    let tbody = document.querySelector("table#vrp_history_table > tbody");
    tbody.replaceChildren(...table_rows);

    let tfoot_pagination = document.querySelector("th#vrp_history_pagination")
    let tfoot_spans = new Array();
    let tfoot_label = document.createElement('SPAN');
    tfoot_label.innerText = 'Page: ';
    tfoot_spans.push(tfoot_label);
    const page_current = Math.floor(offset / numEntries);
    const page_max = Math.floor(RPKI_HISTORY_ENTRIES.length / numEntries);
    for (let off = 0; off < RPKI_HISTORY_ENTRIES.length; off += numEntries) {
        const page_span = create_clickable_pagination_span(off / numEntries, numEntries);
        tfoot_spans.push(page_span);
    }
    tfoot_pagination.replaceChildren(...tfoot_spans);

    // TODO: use window.history.pushState to update the URL including display_offset and display_num_entries
    // Maybe create an abstraction to make it easy to change given URL query-string parameters
}

/**
 * click event handler used by vrp_history_table <tfoot><tr><th><span onclick="...">0</span><span>1</span>...
 */
function display_history_page_onclick_handler (event) {
    const entries_per_page = get_paginate_num_entries_per_page();
    const offset = entries_per_page * this.dataset.page_number;
    display_history_entries(offset);
}

function display_result_caption (elapsed_time, hits, shards) {
    let caption = document.querySelector("#vrp_history_table > caption");
    caption.innerText = `took: ${elapsed_time}ms `
    caption.innerText += ` shards: ${shards}`;
    if (hits >= 10000) {
        caption.innerText += ' hits: >= 10000';
    } else {
        caption.innerText += ` hits: ${hits}`;
    }
    caption.style.color = null; // WTF what is this for?
}

function get_paginate_num_entries_per_page () {
    const input_elem = document.querySelector('input#display_num_entries');
    let retval = parseInt(input_elem.value);
    if (!Number.isInteger(retval)) {
        console.warn(`input#display_num_entries should be integer, but is ${retval}.  Replacing with default (20).`);
        input_elem.value = 20;
        retval = 20;
    }
    return retval;
}

function search_clicked (event) {
    let tbody = document.querySelector("table#vrp_history_table > tbody");
    let caption = document.querySelector("#vrp_history_table > caption");
    caption.innerText = 'Posting query to rpkilog API...';
    caption.style.color = '#e4d802';
    tbody.replaceChildren();

    let copy_fields_to_query = [
        "asn",
        "observation_timestamp_start",
        "observation_timestamp_end",
        "prefix",
    ];
    let query = {
        'paginate_size': 1000,
    };
    // Copy input form fields which require no manipulation (except URI encoding) before posting to API
    for (let field of copy_fields_to_query) {
        let input_element = document.querySelector("#" + field);
        if (input_element.value.length) {
            query[field] = input_element.value;
        }
    }

    let get_params = new URLSearchParams(query)
    fetch(rpkilog_config.api_url + '?' + get_params.toString(), {
        method: 'GET',
        cache: 'no-store',
        headers: {'Accept': 'application/json'},
        mode: 'cors',
    })
    .then(fetch_response => { return fetch_response.json(); } )
    .then(json_body => {
        RPKI_HAPI_RESULT = json_body;
        RPKI_HISTORY_ENTRIES = [];
        for (let entry_json of json_body.hits.hits) {
            let entry_obj = VrpHistoryEntry.new_from_hapi_result_entry(entry_json);
            RPKI_HISTORY_ENTRIES.push(entry_obj);
        }
        display_result_caption(json_body.took, json_body.hits.total.value, json_body._shards.total);
        display_history_entries(0);
        window.history.pushState('', '', '/?' + get_params.toString());
    });
};

document.querySelector("#rpki_history_search_button").addEventListener("click", search_clicked);
addEventListener('DOMContentLoaded', check_for_deeplink_in_url);
