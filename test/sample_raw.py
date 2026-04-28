"""Sample raw Python file for tf_onboard testing."""

import os
import sys


class Animal:
    """A simple animal class."""

    def __init__(self, name, sound):
        self.name = name
        self.sound = sound

    def speak(self):
        return f"{self.name} says {self.sound}"

    def describe(self):
        return f"I am {self.name}"

    def __repr__(self):
        return f"Animal({self.name!r})"


class Dog(Animal):
    """A dog that can fetch."""

    def __init__(self, name):
        super().__init__(name, "woof")
        self.tricks = []

    def learn_trick(self, trick):
        self.tricks.append(trick)

    def perform(self):
        if not self.tricks:
            return f"{self.name} knows no tricks"
        return f"{self.name} performs: {', '.join(self.tricks)}"

    def fetch(self, item):
        return f"{self.name} fetches {item}"


def greet(name):
    return f"Hello, {name}!"


def add(a, b):
    return a + b
