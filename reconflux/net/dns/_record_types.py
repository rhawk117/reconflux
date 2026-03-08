from enum import StrEnum


class DNSRecordType(StrEnum):
    A = 'A'
    AAAA = 'AAAA'
    CNAME = 'CNAME'
    MX = 'MX'
    NS = 'NS'
    PTR = 'PTR'
    SOA = 'SOA'
    SRV = 'SRV'
    TXT = 'TXT'
    CAA = 'CAA'
