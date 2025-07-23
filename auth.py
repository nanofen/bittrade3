class BybitKeys():

    def keys(self, prod=False, env_name=None):
        # test net
        api_key = 'F4KfCrF0sA64QmHMN0'
        api_secret = 'yeKMFDIEqjmgcCUC12WXEF2MXR9GuuG8E204'
        # test lsratio
        if env_name == "lgbm":
            api_key = 'IXSYZLSIYVZSZQLJBZ'
            api_secret = 'MGXNVLJVUAUMAYKCNRSGWQMQNAMCSYMYQZAE'
        # test breakout
        if env_name == "breakout":
            api_key = 'ACIIPYCWDBPFOLAGUH'
            api_secret = 'PGDSRDLTFFMWIRSBLAHNCHFUHWDLOUDNVJJF'
        # test lsratio buy
        if env_name == "lsratio_buy":
            api_key = 'HDXVHANPBSTVCSTMJI'
            api_secret = 'BAUIFNOCVCSVPRZYQXAKJZAKNSNKOTIEBTVD'
        # test lsratio sell
        if env_name == "lsratio_sell":
            api_key = 'NHQVAPDORJZBMVDRJM'
            api_secret = 'VGQKAYROLBRBTVEHWUVAEPGAMGNLGXDQMSMG'
        if prod == True:
            api_key = '3KUIKSitdw8EevMssZ'
            api_secret = 'RL073HbZCCPlqL7i0V3Q50pbXqBY0IXAewDR'
            if env_name == "lgbm":
                api_key = '4C0nNpNCV4wXaFkXZ8'
                api_secret = '9i0K8Slzh5ERbcuokWpb2nX0qOLyGWyQo9j3'

        return api_key, api_secret

class BitbankKeys():

    def keys(self):
        api_key = "2ab46946-165b-42eb-9156-5be723430532"
        api_secret = "b54388bd09322aa323899cd953d6760b7c933207b4b2dc3f78ba01536c8d2363"

        return api_key, api_secret

class GMOCoinKeys():

    def keys(self):
        api_key = "5DdLwmIYKW5OWx8JOYyhBSSkWOxKkrNc"
        api_secret = "/wuNzP8kGZ3QtLAhlhtBaCmE6jveYY0WhPT5f3OXyKXZ6ffMmFVOWWa/QOS/r62t"

        return api_key, api_secret
