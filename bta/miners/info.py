from bta.miners import Miner


@Miner.register
class Info(Miner):
    _name_ = "info"
    _desc_ = "Informations about AD tables"
    @classmethod
    def create_arg_subparser(cls, parser):
        parser.add_argument("-v", "--verbose", help="verbose output", action="store_true")

    def __init__(self, backend):
        Miner.__init__(self, backend)
        self.dblog = backend.open_table("log")
    
    def run(self, options, doc):
        s1 = doc.create_subsection("logs")
        lst = s1.create_list("logs")

        c = self.dblog.find().sort("date",1)
        for entry in c:
            lst.add("%(date)s: %(args)s" % entry)
            lst2 = lst.create_list("actions")
            for a in entry["actions"]:
                lst2.add("%(date)s: %(action)s" % a)
            lst2.finished()
        lst.finished()
        s1.finished()

        s2 = doc.create_subsection("tables")

        tbl = s2.create_table("datatable")
        tbl.add(("number of records", self.datatable.count()))
        tbl.add(("number of columns", self.datatable_meta.count()))
        tbl.finished()
        tbl = s2.create_table("sd_table")
        tbl.add(("number of records", self.sd_table.count()))
        tbl.finished()
        tbl = s2.create_table("link_table")
        tbl.add(("number of records", self.link_table.count()))
        tbl.finished()

        if options.verbose:
            tbl = s2.create_table("datatable columns")
            tbl.add(("name", "attname", "type", "number of records"))
            tbl.add()
            for r in self.datatable_meta.find():
                tbl.add((r["name"], r["attname"], r["type"],r["count"] ))
            tbl.finished()
        
        if options.verbose:
            tbl = s2.create_table("categories")
            tbl.add(("id", "name", "number of records"))
            tbl.add()
            for r in self.category.find():
                tbl.add((r["id"], r["name"], self.datatable.find({"objectCategory": r["id"]}).count()))
            tbl.finished()

    def assert_consistency(self):
        Miner.assert_consistency(self)
        Miner.assert_field_exists(self.datatable,"objectCategory")
        Miner.assert_field_type(self.datatable,"objectCategory", int)
