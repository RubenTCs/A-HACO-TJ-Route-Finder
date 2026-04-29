import os
import gtfs_kit as gk
from django.conf import settings


class GTFSHelper:
    def __init__(self, feed_path):
        self.feed_path = feed_path
        self.__feed = None
        self._routes = None
        self._stops = None
        self._stop_times = None
        self._trips = None
        self._frequencies = None
        self._calendar = None
        self._fare_attributes = None
        self._fare_rules = None
        self._shapes = None
        self._transfers = None

    def __get_feed(self):
        if self.__feed is None:
            self.__feed = gk.read_feed(self.feed_path, dist_units="km")
        return self.__feed

    @property
    def routes(self):
        if self._routes is None:
            self._routes = self.__get_feed().get_routes()
        return self._routes

    @property
    def stops(self):
        if self._stops is None:
            self._stops = self.__get_feed().get_stops()
        return self._stops

    @property
    def stop_times(self):
        if self._stop_times is None:
            self._stop_times = self.__get_feed().get_stop_times()
        return self._stop_times

    @property
    def trips(self):
        if self._trips is None:
            self._trips = self.__get_feed().get_trips()
        return self._trips

    @property
    def frequencies(self):
        if self._frequencies is None:
            self._frequencies = self.__get_feed().frequencies
        return self._frequencies

    @property
    def calendar(self):
        if self._calendar is None:
            self._calendar = self.__get_feed().calendar
        return self._calendar

    @property
    def fare_attributes(self):
        if self._fare_attributes is None:
            self._fare_attributes = self.__get_feed().fare_attributes
        return self._fare_attributes

    @property
    def fare_rules(self):
        if self._fare_rules is None:
            self._fare_rules = self.__get_feed().fare_rules
        return self._fare_rules

    @property
    def shapes(self):
        if self._shapes is None:
            self._shapes = self.__get_feed().shapes
        return self._shapes
    
    @property
    def transfer(self):
        if self._transfers is None:
            self._transfers = self.__get_feed().transfers
        return self._transfers


gtfsHelper = GTFSHelper(
    os.path.join(settings.BASE_DIR, "myapp", "static", "data", "GTFS_Preprocessed.zip")
)
