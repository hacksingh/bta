# This file is part of the BTA toolset
# (c) Airbus Group CERT, Airbus Group Innovations and Airbus DS CyberSecurity

from bta.miner import Miner
from bta.miners import list_ACE
import datetime
from bta.tools.mtools import Sid
from bta.tools.WellKnownSID import SID2StringFull, SID2String


@Miner.register
class ListGroup(Miner):
    _name_ = "ListGroup"
    _desc_ = "List group membership"
    _uses_ = ["raw.datatable", "raw.sd_table", "raw.link_table", "special.categories", "raw.guid", "raw.linkid"]
    groups_already_seen = {}
    class_cache = dict()

    @classmethod
    def create_arg_subparser(cls, parser):
        parser.add_argument("--match", help="Look only for groups matching REGEX", metavar="REGEX")
        parser.add_argument("--noresolve", help="Do not resolve SID", action="store_true")
        parser.add_argument("--verbose", help="Show also deleted users time and RID", action="store_true")

    def get_members_of(self, grpsid, recursive=False):
        group = self.datatable.find_one({'objectSid': grpsid.split(":")[0]})
        if not group:
            return set()
        members = set()
        for link in self.link_table.find({'link_DNT': group['DNT_col']}):
            deleted = False
            if 'link_deltime' in link and link['link_deltime'].year > 1970:
                deleted = link['link_deltime']
            row = self.datatable.find_one({'DNT_col': link['backlink_DNT']})
            if not row:
                members.add('[no entry %d found]' % link['backlink_DNT'])
                continue
            objectClass = row['objectClass']
            if u'1.2.840.113556.1.5.8' in objectClass:
                sid = row['objectSid']
                if sid not in self.groups_already_seen:
                    self.groups_already_seen[sid] = True
                    newmembers = self.get_members_of(sid + ":" + grpsid, recursive=True)
                    if len(newmembers) > 0:
                        members.update(newmembers)
                    else:
                        # A group may have a Member or ManagedBy relationship with another
                        members.add(('Empty group', link['link_base'], sid, deleted, grpsid, SID2StringFull(sid, self.guid), row['sAMAccountName']))
            else:
                # Not all relevant rows have an objectSid value - ex.
                # ms-Exch-Dynamic-Distribution-List or Contact
                sid = row.get('objectSid', '(no sid)')
                objectType = self.get_objectClass_name(row['objectClass'][0])
                fromgrp = grpsid if recursive else ''
                name = row['name']
                samAccountName = row.get('sAMAccountName', '(no SAM account name)')
                membership = (objectType, link['link_base'], sid, deleted, fromgrp, name, samAccountName)
                members.add(membership)
        return members

    def get_objectClass_name(self, oc):
        """ Cache object class to class name mapping """
        r = ListGroup.class_cache.get(oc)
        if r:
            return r
        r = self.datatable.find_one({'governsID': oc})['name']
        ListGroup.class_cache[oc] = r
        return r

    def getInfo_fromSid(self, sid):
        return self.datatable.find_one({'objectSid': sid})

    def find_dn(self, r):
        if not r:
            return ""
        cn = r.get("cn") or r.get("name")
        if cn is None or cn.startswith("$ROOT_OBJECT$"):
            return ""
        r2 = self.datatable.find_one({"DNT_col": r["PDNT_col"]})
        return self.find_dn(r2)+"."+cn

    def checkACE(self, membersid):
        secDesc = int(self.datatable.find_one({"objectSid": membersid})['nTSecurityDescriptor'])
        hdlACE = list_ACE.ListACE(self.backend)
        securitydescriptor = hdlACE.getSecurityDescriptor(secDesc)
        aceList = hdlACE.extractACE(securitydescriptor)

        Mylist = list()
        for ace in aceList:
            info = self.getInfo_fromSid(ace['SID'])
            if info is None:
                trustee_cn = trustee_string = "NULLOBJECT-%s" % ace['SID']
            else:
                if "cn" in info:
                    trustee_cn = info['cn']
                    trustee_string = SID2String(info['cn'])
                else:
                    trustee_string = trustee_cn = info['name']
            trustee = trustee_cn if trustee_cn == trustee_string else "%s (%s)" % (trustee_cn, trustee_string)
            info2 = self.getInfo_fromSid(membersid)
            subject = info2['cn']
            if ace['ObjectType']:
                objtype = hdlACE.type2human(ace['ObjectType'])
            else:
                objtype = '(none)'
            Mylist.append([trustee, subject, ace['Type'], objtype])
        return Mylist

    def run(self, options, doc):
        def deleted_last(l):
            deleteditems = []
            for i in l:
                if not i[2]:
                    yield i
                else:
                    deleteditems.append(i)
            for i in deleteditems:
                yield i

        match = {'objectClass': '1.2.840.113556.1.5.8'}

        doc.add("List of groups matching [%s]" % (options.match if options.match else 'any group'))
        if options.match:
            match = {"$and": [{'objectClass': '1.2.840.113556.1.5.8'},
                              {"$or": [{"name": {"$regex": options.match}},
                                       {"objectSid": {"$regex": options.match}}
                                      ]
                              }]
                    }

        groups = {}
        # Recursively find members of matching groups.
        for group in self.datatable.find(match):
            groups[group['objectSid']] = self.get_members_of(group['objectSid'])

        listemptyGroup = []
        for groupSid, membership in groups.items():
            if len(membership) == 0:
                listemptyGroup.append(groupSid)
                continue
            info = self.getInfo_fromSid(groupSid)
            groupCN = info['cn']
            guid = info['objectGUID']
            sec = doc.create_subsection("Group %s" % groupCN)
            sec.add("sid = %s" % groupSid)
            sec.add("guid = %s" % guid)
            sec.add("dn = %s" % self.find_dn(info))

            # 2 tables: 1 -> member users, 1 -> rest
            memberUsersTable = list()
            otherLinkedTable = list()
            for objectType, linkBase, sid, deleted, fromgrp, name, samAccountName in deleted_last(membership):
                fromgrp = fromgrp.split(":")[0]
                sidobj = Sid(sid, self.datatable)
                if fromgrp:
                    fromgrp = Sid(fromgrp, self.datatable)
                if objectType == 'User' and linkBase == 1:  # member user
                    flags = sidobj.getUserAccountControl()
                    memberUsersTable.append((name, samAccountName, deleted or '', flags, fromgrp))
                else:
                    linkType = self.linkid.find_one({'linkid': linkBase*2})['name']
                    otherLinkedTable.append((objectType, linkType, name, samAccountName, deleted or '', fromgrp))

            if len(memberUsersTable) != 0:
                headers = ['Name', 'SAM Account Name', 'Deletion', 'Flags', 'Recursive']
                table = sec.create_table("Members users of %s" % groupCN)
                table.add(headers)
                table.add()
                for elem in memberUsersTable:
                    table.add(elem)
                table.finished()

            if len(otherLinkedTable) != 0:
                headers = ['Object Type', 'Link Type', 'Name', 'SAM Account Name', 'Deletion', 'Recursive']
                table = sec.create_table("Other objects linked to group %s" % groupCN)
                table.add(headers)
                table.add()
                for elem in otherLinkedTable:
                    table.add(elem)
                table.finished()

            # ACEs for users
            for objectType, linkBase, sid, deleted, fromgrp, name, samAccountName in deleted_last(membership):
                if objectType != 'User':
                    continue
                sec.add("User %s (%s)" % (name, sid))
                table = sec.create_table("ACE of %s" % name)
                table.add(["Trustee", "Member", "ACE Type", "Object type"])
                table.add()
                listACE = self.checkACE(sid)
                for ace in listACE:
                    table.add(ace)
                table.finished()
            sec.finished()

        if len(listemptyGroup) > 0:
            headers = ['Group', 'SID', 'Guid']
            table = doc.create_table("Empty groups")
            table.add(headers)
            table.add()
            for groupSid in listemptyGroup:
                info = self.getInfo_fromSid(groupSid)
                name = info['cn']
                guid = info['objectGUID']
                table.add((name, groupSid, guid))
            table.finished()

    def assert_consistency(self):
        Miner.assert_consistency(self)
        self.assert_field_type(self.datatable, "objectSid", str, unicode)
        self.assert_field_type(self.datatable, "DNT_col", int)
        self.assert_field_type(self.datatable, "PDNT_col", int)
        self.assert_field_type(self.datatable, "objectCategory", int)
        self.assert_field_type(self.datatable, "cn", str, unicode)
        self.assert_field_type(self.datatable, "name", str, unicode)
        self.assert_field_type(self.datatable, "objectGUID", str, unicode)
        self.assert_field_type(self.sd_table, "link_DNT", int)
        self.assert_field_type(self.sd_table, "link_deltime", datetime.datetime)
        self.assert_field_type(self.sd_table, "backlink_DNT", int)
