import logging
from decimal import Decimal
from random import randint
from time import time
from typing import cast

from geniusweb.actions.Accept import Accept
from geniusweb.actions.Action import Action
from geniusweb.actions.Offer import Offer
from geniusweb.actions.PartyId import PartyId
from geniusweb.bidspace.AllBidsList import AllBidsList
from geniusweb.inform.ActionDone import ActionDone
from geniusweb.inform.Finished import Finished
from geniusweb.inform.Inform import Inform
from geniusweb.inform.Settings import Settings
from geniusweb.inform.YourTurn import YourTurn
from geniusweb.issuevalue.Bid import Bid
from geniusweb.issuevalue.Domain import Domain
from geniusweb.party.Capabilities import Capabilities
from geniusweb.party.DefaultParty import DefaultParty
from geniusweb.profile.utilityspace.LinearAdditiveUtilitySpace import (
    LinearAdditiveUtilitySpace,
)
from geniusweb.profileconnection.ProfileConnectionFactory import (
    ProfileConnectionFactory,
)
from geniusweb.progress.ProgressTime import ProgressTime
from geniusweb.references.Parameters import Parameters
from tudelft_utilities_logging.ReportToLogger import ReportToLogger

from geniusweb.opponentmodel import FrequencyOpponentModel

class BattleDroid(DefaultParty):
    """
    Template of a Python geniusweb agent.
    """

    def __init__(self):
        super().__init__()
        self.logger: ReportToLogger = self.getReporter()

        self.domain: Domain = None
        self.parameters: Parameters = None
        self.profile: LinearAdditiveUtilitySpace = None
        self.progress: ProgressTime = None
        self.me: PartyId = None
        self.other: str = None
        self.settings: Settings = None
        self.storage_dir: str = None
        self.bid_history: list = []
        self.value_frequencies: list = []
        self.issue_weights: list = []
        self.issue_change_counter: list = []
        self.last_received_bid: Bid = None
        
        self.utility_last_received_bid: float = 1.0
        self.utility_last_sent_bid: float = 1.0

        self.logger.log(logging.INFO, "party is initialized")

    def notifyChange(self, data: Inform):
        """MUST BE IMPLEMENTED
        This is the entry point of all interaction with your agent after is has been initialised.
        How to handle the received data is based on its class type.

        Args:
            info (Inform): Contains either a request for action or information.
        """

        # a Settings message is the first message that will be send to your
        # agent containing all the information about the negotiation session.
        if isinstance(data, Settings):
            self.settings = cast(Settings, data)
            self.me = self.settings.getID()

            # progress towards the deadline has to be tracked manually through the use of the Progress object
            self.progress = self.settings.getProgress()

            self.parameters = self.settings.getParameters()
            self.storage_dir = self.parameters.get("storage_dir")

            # the profile contains the preferences of the agent over the domain
            profile_connection = ProfileConnectionFactory.create(
                data.getProfile().getURI(), self.getReporter()
            )
            self.profile = profile_connection.getProfile()
            self.domain = self.profile.getDomain()
            profile_connection.close()

        # ActionDone informs you of an action (an offer or an accept)
        # that is performed by one of the agents (including yourself).
        elif isinstance(data, ActionDone):
            action = cast(ActionDone, data).getAction()
            actor = action.getActor()

            # ignore action if it is our action
            if actor != self.me:
                # obtain the name of the opponent, cutting of the position ID.
                self.other = str(actor).rsplit("_", 1)[0]

                # process action done by opponent
                self.opponent_action(action)
        # YourTurn notifies you that it is your turn to act
        elif isinstance(data, YourTurn):
            # execute a turn
            self.my_turn()

        # Finished will be send if the negotiation has ended (through agreement or deadline)
        elif isinstance(data, Finished):
            self.save_data()
            # terminate the agent MUST BE CALLED
            self.logger.log(logging.INFO, "party is terminating:")
            super().terminate()
        else:
            self.logger.log(logging.WARNING, "Ignoring unknown info " + str(data))

    def getCapabilities(self) -> Capabilities:
        """MUST BE IMPLEMENTED
        Method to indicate to the protocol what the capabilities of this agent are.
        Leave it as is for the ANL 2022 competition

        Returns:
            Capabilities: Capabilities representation class
        """
        return Capabilities(
            set(["SAOP"]),
            set(["geniusweb.profile.utilityspace.LinearAdditive"]),
        )

    def send_action(self, action: Action):
        """Sends an action to the opponent(s)

        Args:
            action (Action): action of this agent
        """
        self.getConnection().send(action)

    # give a description of your agent
    def getDescription(self) -> str:
        """MUST BE IMPLEMENTED
        Returns a description of your agent. 1 or 2 sentences.

        Returns:
            str: Agent description
        """
        return "Battle Droid beep beep"

    def opponent_action(self, action):
        """Process an action that was received from the opponent.

        Args:
            action (Action): action of opponent
        """
        if isinstance(action, Offer):
            bid: Bid = cast(Offer, action).getBid()

            # Set bid as last received
            self.last_received_bid = bid

            # How many issues are there in the bid.
            issues_length: int = len(self.last_received_bid.getIssues())
            # The values for every issue.
            issue_values: list = list(self.last_received_bid.getIssueValues().values())
            self.bid_history.append(issue_values)

            # Initializes the values for the issue weights, the value tracker and the frequency of the issue.
            if not self.issue_weights:
                for i in range(issues_length):
                    # 1.0 / amount of issues to set it to an even division.
                    self.issue_weights.append(1.0 / issues_length)
                    # Set how often an issue has changed to 1.0.
                    self.issue_change_counter.append(1.0)
                    # Set the frequencies of the issue values to 1.0.
                    self.value_frequencies.append({issue_values[i]: 1.0})

            else:
                # go through every issue in the received bid and update the frequency values.
                for i, issue_values_last_bid in enumerate(self.last_received_bid.getIssueValues().values()):
                    # If the values in the last received bid have changed with the previous bid, indicate it is less important
                    if self.bid_history[-1][i] != issue_values_last_bid:
                        self.issue_change_counter[i] *= 2
        
                    # Update the weight of the issue
                    change_total = sum(self.issue_change_counter)
                    issue_weight_sum = change_total - self.issue_change_counter[i]
                    issue_weight_denominator = change_total * (len(self.last_received_bid.getIssueValues()) - 1)
                    self.issue_weights[i] = issue_weight_sum / issue_weight_denominator
    
                    # Increment the frequency of the issue values
                    self.value_frequencies[i][issue_values_last_bid] = self.value_frequencies[i].get(issue_values_last_bid, 0) + 1
            

    def my_turn(self):
        """This method is called when it is our turn. It should decide upon an action
        to perform and send this action to the opponent.
        """

        # calculates the utility of the last received bid.
        utility: float = 0
        
        if not self.last_received_bid:
            utility = 0.95
        else:
            for i in range(len(self.last_received_bid.getIssues())):
                utility += self.issue_weights[i] * (self.value_frequencies[i][list(self.last_received_bid.getIssueValues().values())[i]] / sum(self.value_frequencies[i].values()))
        
        # Find a bid before the accept condition to compare the last received bid with our own next bid.
        bid: Bid = self.find_bid(utility)

        # check if the last received offer is good enough.
        if self.accept_condition(self.last_received_bid):
            # if so, accept the offer
            action = Accept(self.me, self.last_received_bid)
        else:
            # if not, propose a counter offer.
            action = Offer(self.me, bid)

        self.utility_last_received_bid = utility
        # send the action
        self.send_action(action)

    def save_data(self):
        """This method is called after the negotiation is finished. It can be used to store data
        for learning capabilities. Note that no extensive calculations can be done within this method.
        Taking too much time might result in your agent being killed, so use it for storage only.
        """
        data = "Data for learning (see README.md)"
        with open(f"{self.storage_dir}/data.md", "w") as f:
            f.write(data)

    def accept_condition(self, bid: Bid) -> bool:
        if bid is None:
            return False
        # progress of the negotiation session between 0 and 1 (1 is deadline)
        progress: float = self.progress.get(time() * 1000)


        if self.profile.getReservationBid() is None:
            reservation = 0.7
        else:
            reservation = self.profile.getUtility(self.profile.getReservationBid())

        if self.profile.getUtility(bid) >= 0.99:
            return True
        
        # "The family of curves with beta > 1 are called Boulware, whereas beta < 1 are termed Conceder"
        # Source for formula: https://web.fe.up.pt/~eol/schaefer/diplom/TacticsAndStrategies.htm
        
        beta: float = 0.005
        k: float = 0.18
        utility: float = k + (1-k) * pow(progress, 1/beta)
        if self.profile.getUtility(bid) >= 1 - utility:
            return True
        
        # Old code
        # beta: float = 0.000000001
        # x_0: float = 0.9
        # g_r: float = x_0 + (1.0 - x_0) * pow(progress, (1.0 / beta))
        # x_min: float = 0.8
        # x_max: float = 1.0
        # utility_x: float = x_min + (1.0 - g_r) * (x_max - x_min)
        # if self.profile.getUtility(bid) >= utility_x:
        #     return True

        # very basic approach that accepts if the offer is valued above the reservation value and
        # 99% of the time towards the deadline has passed
        conditions = [
            self.profile.getUtility(bid) > reservation,
            progress >= 0.99,
        ]
        
        return all(conditions)

    def find_bid(self, utility: float) -> Bid:
        """This method is called when its our turn. We use the returned value to compare it with
        the last received bid and then either accept the receid bid or send this bid. We use a 
        tit-for-tat strategy.
        """
        # Compose a list of all possible bids
        domain = self.profile.getDomain()
        # Get all possible bids
        all_bids = AllBidsList(domain)
        
        # Calculate the difference between the last received bid utility and the current utility
        diff_received_utility: float = self.utility_last_received_bid - utility

        for _ in range(5000):
            # Choose a random bid
            bid = all_bids.get(randint(0, all_bids.size() - 1))
            # Calculate the difference between the last sent bid utility and current bid utility
            diff_sent_utility = Decimal(self.utility_last_sent_bid) - self.profile.getUtility(bid)
            # Check if the conditions for a valid bid are met
            conditions = [
                -0.2 < diff_sent_utility  - (Decimal(diff_received_utility) * Decimal(0.3)) < 0.05,
                Decimal(self.utility_last_sent_bid) - self.profile.getUtility(bid) < 0.1
            ]
            if all(conditions):
                # If all conditions are met, return the bid
                self.utility_last_sent_bid = self.profile.getUtility(bid)
                return bid
        
        # If no valid bid is found, loop through possible bids again
        for _ in range(5000):
            # Choose a random bid
            bid = all_bids.get(randint(0, all_bids.size() - 1))
            # Check if the new bid utility is close to or better than the last sent bid utility
            if self.utility_last_sent_bid - self.profile.getUtility(bid) < 0.1:
                self.utility_last_sent_bid = self.profile.getUtility(bid)
                return bid
            
        # If no valid bid is found, choose a random bid
        bid = all_bids.get(randint(0, all_bids.size() - 1))
        self.utility_last_sent_bid = self.profile.getUtility(bid)
        return bid