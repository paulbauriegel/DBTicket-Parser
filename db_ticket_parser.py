#!/usr/bin/env python
# coding=utf-8

"""
db_ticket_parser.py

Extract the important information from the Deutsche Bahn Online-Tickets.
"""

import csv
import glob
import math
import os
import pdfquery
import re
import sys
from datetime import datetime
from functools import reduce

from prettytable import PrettyTable

ticket_table_header = []
ticket_table = []

# Helper Functions
def get_time(text):
    try:
        found = re.search('[0-9]{2}:[0-9]{2}', text).group(0)
    except AttributeError:
        found = ''
    return found


def get_date(text):
    try:
        found = re.search('[0-9]{2}.[0-9]{2}.[0-9]{4}', text).group(0)
    except AttributeError:
        found = ''
    return found


def delete_all(text, elem):
    return reduce(lambda x, y: x.replace(y, ''), elem, text).strip()


def trunc_stationname(text):
    return reduce(lambda x, y: x.replace(y, ''), ["+City", " RNV"] + ['Hinfahrt: ', 'Rückfahrt: '], text.split(", ")[0]).strip()


def time_diff(start, end):
    if start == "" or end == "":   # Error Handling empty String
        return ""
    start = datetime.strptime(start, "%H:%M")
    end = datetime.strptime(end, "%H:%M")
    time_delta = int((end - start).total_seconds())
    #time_delta = abs(time_delta) if time_delta < 0 else time_delta
    days, time_delta = divmod(time_delta, 86400)
    hours, time_delta = divmod(time_delta, 3600)
    minutes, seconds = divmod(time_delta, 60)
    if days == 0:
        return "{:02d}:{:02d}".format(hours, minutes)
    else:
        return "{} days, {:02d}:{:02d}".format(days, hours, minutes)


# Function to find last Tim in PDF
def arrival_time(pdf):
    rueck_head = []
    go_up = 0
    while len(rueck_head) <= 0:
        go_up+=10
        rueck_head = pdf.pq('LTTextLineHorizontal:in_bbox("%s, %s, %s, %s")' % (10, 0, 350, go_up)) \
            .filter(lambda i, e: e.layout.get_text().startswith('ab ') and ":" in e.layout.get_text())
        if go_up > 1000:
            go_up = -1
            break
    return go_up


def parse_time_box(pdf, x0, y0, x1, y1, w):
    hin_line = pdf.pq('LTTextLineHorizontal:in_bbox("%s, %s, %s, %s")' % (x0, y0, x1, y1)).filter(lambda i, e: e.layout.get_text()\
    .strip().startswith(w))[0].layout.get_text()
    return get_time(hin_line)


# Add Entry to Table
def add_tableentry(modi, ticket_id, price, validity, ticket_type, klasse, pers, hin_ab_ort, hin_abfahrt, hin_an_ort,
                   hin_ankunft, rueck_hin, rueck_abfahrt,rueck_nach, rueck_ankunft, zugtyp):
    if modi == "all":
        global ticket_table
        ticket_table += [[ticket_id, price, validity, ticket_type, klasse, pers,
                                          re.sub(r"\d{2}:\d{2}", r"(\g<0>)", hin_ab_ort + hin_abfahrt),
                                          re.sub(r"\d{2}:\d{2}", r"(\g<0>)", hin_an_ort + hin_ankunft),
                                          time_diff(hin_abfahrt, hin_ankunft),
                                          re.sub(r"\d{2}:\d{2}", r"(\g<0>)", rueck_hin + rueck_abfahrt),
                                          re.sub(r"\d{2}:\d{2}", r"(\g<0>)", rueck_nach + rueck_ankunft),
                                          time_diff(rueck_abfahrt, rueck_ankunft), zugtyp]]
        global ticket_table_header
        ticket_table_header = ['Auftrag', 'Summe', 'Datum', 'Ticket', 'Kl.', 'Pers.', 'Hin - Ab', 'Hin - An',
                                    'Hin - Dauer', 'Rück - Ab','Rück - An', 'Rück - Dauer', 'Zugtyp']
    elif modi == "steuer":
        pass
    else:
        print("\nUnknown Modi: Use 'all' or 'steuer'")
        sys.exit(0)

# Display Function
def show_table():
    print("\n")
    t = PrettyTable(ticket_table_header)
    for i in range(len(ticket_table)):
        t.add_row(ticket_table[i])
    print(t)


# Export Function
def write_table():
    with open('bahn.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter=';')
        for i in range(len(ticket_table)):
            writer.writerow(ticket_table[i])


# Main Program
# Modi e (all, steuer)
def ticket_parser(directory_name="Bahn", limit_year="", modi="all"):
    try:
        os.chdir(directory_name)
    except:                         # Exception nicht weiter spezifiziert weil OS abhänig
        print(os.getcwd())
        raise

    ticket_table = {}
    ticket_count = 0

    for filename in glob.iglob('*.pdf'):
        print('.', end='', flush=True)
        ticket_count += 1

        pdf = pdfquery.PDFQuery(filename)
        pdf.load(0)

        # Gültigkeit - Startdatum
        validity = pdf.tree.xpath("//LTTextLineHorizontal[starts-with(.,'Gültigkeit: ') or "
                                  "starts-with(.,'Fahrtantritt am ')]")[0].text
        validity = get_date(validity)
        if limit_year not in validity:              # Limit year option
            continue

        # TicketArt
        ticket = pdf.tree.xpath("//LTTextLineHorizontal[starts-with(.,'Flexpreis') or starts-with(.,'Sparpreis') or "
                       "starts-with(.,'bahn.bonus Freifahrt') or starts-with(.,'Normalpreis')][1]")[0].text.split('(')
        ticket_option = ticket[0]
        ticket_type = ticket[1][:-2].replace("Hin- und Rückfahrt", "2 Wege").replace("Einfache Fahrt", "Einfach")

        # Erkenne Routenelemene
        # ... sind unen begrenzt von der Über - Info oder einem Satz
        infobox_bm = pdf.pq('LTTextLineHorizontal:contains("Über: ")')     # Nutze Zwischenstop-Info als untere Schranke
        umtausch_bool = (len(infobox_bm) == 0)                             # Existiert die Zwischenstop-Info nicht ...
        if umtausch_bool:
            infobox_bm = pdf.pq('LTTextLineHorizontal'                 # ... nutze Satz als untere Schranke
                                ':contains("Umtausch/Erstattung kostenlos bis 1 Tag vor Reiseantritt (Hinfahrt).")')
            #UMTAUSCH / ERSTATTUNG KOSTENPFLICHTIG AB 1. GELTUNGSTAG
        # ... sind nach oben begrenzt durch den 'Erw.'-Text
        infobox_tp = math.ceil(float(pdf.tree.xpath("//LTTextLineHorizontal[starts-with(.,'Erw:')]")[0].layout.bbox[1]))
        route = pdf.pq('LTTextLineHorizontal:in_bbox("%s, %s, %s, %s")' # Startpunkt unten links - Endpunkt oben rechts
                       % (float(infobox_bm.attr('x0'))-5, float(infobox_bm.attr('y0'))-5, 350, infobox_tp+5))

        # Zwischenstopps
        if umtausch_bool:
            ueber = "Keine Zwischenstopps"
        else:
            ueber = route.filter(lambda i, e: all(s not in e.layout.get_text()    # Wörter welche nicht vorkommen dürfen
                                 for s in ['Hinfahrt:', 'Über:','Rückfahrt:', 'Umtausch/Erstattung']) and
                                 any(s in e.layout.get_text() for s in ['VIA:', '*', ':']))[0].layout.get_text().strip()
            ueber = delete_all(ueber, ['VIA: '])

        # Reiseverbindung - Boxen
        hin_head = pdf.tree.xpath("//LTTextLineHorizontal"
                                       "[contains(.,'Ihre Reiseverbindung und Reservierung Hinfahrt am')]")[0]
        rueck_head = pdf.tree.xpath("//LTTextLineHorizontal"
                                    "[contains(.,'Ihre Reiseverbindung und Reservierung Rückfahrt am')]")
        rueck_onpage = len(rueck_head) > 0
        if rueck_onpage:
            rueck_head = rueck_head[0]

        # Hinfahrt
        # ... Abfahrtzeit
        hin_abfahrt = parse_time_box(pdf, hin_head.layout.bbox[0], hin_head.layout.bbox[1]-35,
                                     hin_head.layout.bbox[2], hin_head.layout.bbox[1], 'ab ')
        # ... Ankunftzeit
        if not rueck_onpage:
            hin_ankunft = parse_time_box(pdf, hin_head.layout.bbox[0], 0 , hin_head.layout.bbox[2],
                                         arrival_time(pdf), 'an ')
        else:
            hin_ankunft = parse_time_box(pdf, rueck_head.layout.bbox[0], rueck_head.layout.bbox[3],
                                         rueck_head.layout.bbox[2], rueck_head.layout.bbox[3]+25, 'an ')
        # ... Abfahrtort
        hin_ab_ort = route.filter(lambda i, e: 'Hinfahrt:' in e.layout.get_text())[0].layout.get_text()
        hin_ab_ort = trunc_stationname(hin_ab_ort)
        # ... Ankunftort
        hin_an_ort = route.filter(lambda i, e: all(s not in e.layout.get_text() for s in ['Hinfahrt:', 'Über:',
                                   'Rückfahrt:', 'Umtausch/Erstattung',hin_ab_ort, ueber]))[0].layout.get_text()
        hin_an_ort = trunc_stationname(hin_an_ort)

        # Rückfahrt
        if "Einfach" in ticket_type:
            rueck_hin = ""
            rueck_nach = ""
        else:
            rueck_hin = route.filter(lambda i, e: 'Rückfahrt:' in e.layout.get_text())[0].layout.get_text()
            rueck_hin = trunc_stationname(rueck_hin)
            rueck_nach = route.filter(lambda i, e: all(s not in e.layout.get_text() for s in ['Hinfahrt:', 'Über:',
                                                                                              'Rückfahrt:','Umtausch/Erstattung',rueck_hin, ueber]))[0].layout.get_text()
            rueck_nach = trunc_stationname(rueck_nach)

        # Ticketpreis
        label_price = pdf.pq('LTTextLineHorizontal:contains("Summe")')
        price = pdf.pq('LTTextLineHorizontal:in_bbox("%s, %s, %s, %s")' % (float(label_price.attr('x0')) + 100,
                       float(label_price.attr('y0')), float(label_price.attr('x0')) + 150,
                       float(label_price.attr('y0')) + 15)).text()

        # Auftragsnummer
        ticket_id = pdf.pq('LTTextLineHorizontal:overlaps_bbox("36, 19, 72, 28")').text()

        # Klasse
        klasse_box = pdf.tree.xpath("//LTTextLineHorizontal[starts-with(.,'Klasse:')][1]")[0].layout.bbox
        klasse = pdf.pq('LTTextLineHorizontal:overlaps_bbox("%s, %s, %s, %s")' %
                        (klasse_box[2], klasse_box[1], klasse_box[2]+50, klasse_box[3])).text().strip()

        # Personenanzahl
        pers_box = pdf.tree.xpath("//LTTextLineHorizontal[starts-with(.,'Klasse:')][1]")[0].layout.bbox
        pers = pdf.pq('LTTextLineHorizontal:overlaps_bbox("%s, %s, %s, %s")' %
                        (klasse_box[2], klasse_box[1], klasse_box[2]+200, klasse_box[3])).text().split(",")[0].strip()

        # Zugtyp
        zugtyp = pdf.tree.xpath("//LTTextLineHorizontal[contains(.,'Fahrkarte')][1]")[0].text \
            .replace("Fahrkarte", "").strip()
        zugtyp = "RE/RB" if zugtyp == "" else zugtyp

        # Rückfahrt - Zeit
        rueck_abfahrt = ""
        rueck_ankunft = ""
        if not ("Einfach" in ticket_type):
            if not rueck_onpage:
                pdf.load(1)
                rueck_head = pdf.tree.xpath("//LTTextLineHorizontal"
                                            "[contains(.,'Ihre Reiseverbindung und Reservierung Rückfahrt am')]")[0]
            # Abfahrt
            rueck_abfahrt = parse_time_box(pdf, rueck_head.layout.bbox[0], rueck_head.layout.bbox[1]-50,
                                           rueck_head.layout.bbox[2], rueck_head.layout.bbox[1], 'ab ')
            # Ankunft
            rueck_ankunft = parse_time_box(pdf, rueck_head.layout.bbox[0], 0 , rueck_head.layout.bbox[2],
                                           arrival_time(pdf), 'an ')
        # Add Row
        add_tableentry(modi, ticket_id, price, validity, ticket_type, klasse, pers, hin_ab_ort, hin_abfahrt, hin_an_ort,
                       hin_ankunft, rueck_hin, rueck_abfahrt, rueck_nach, rueck_ankunft, zugtyp)
    show_table()
    write_table()


if __name__ == '__main__':
    try:
        if len(sys.argv)>1:
            ticket_parser(sys.argv[1])
        else:
            ticket_parser()
    except KeyboardInterrupt:
        print('\nBerechnung abgebrochen')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)

# TODO differnt modi -> Steuer oder all
# TODO Refractoring
            # Make it a class
            # Math floor useful
            # Each attribute Function useful?
            # Statt Satz Zahlungspositionen und Preis bis ????